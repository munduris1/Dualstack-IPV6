import boto3
import json
import logging
from botocore.config import Config
from ipaddress import IPv6Network

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(process)s] [%(levelname)s] [%(funcName)s] %(message)s')
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)

def enable_ipv6_cidr_for_vpc(ec2, vpc_id):
    """
    Enable IPv6 CIDR for the specified VPC if not already enabled.
    
    Parameters:
        ec2: Boto3 EC2 client.
        vpc_id: ID of the VPC.
        
    Returns:
        The IPv6 CIDR block assigned to the VPC.
    """
    response = ec2.describe_vpcs(VpcIds=[vpc_id])
    vpc = response['Vpcs'][0]
    ipv6_cidr_block_associations = vpc.get('Ipv6CidrBlockAssociationSet', [])
    
    if not ipv6_cidr_block_associations:
        # Assign an Amazon provided IPv6 CIDR block to the VPC
        response = ec2.associate_vpc_cidr_block(VpcId=vpc_id, AmazonProvidedIpv6CidrBlock=True)
        # Describe VPC again to get the newly assigned IPv6 CIDR block
        resp = ec2.describe_vpcs(VpcIds=[vpc_id])
        vpcs = resp.get('Vpcs', [])
        vpc = vpcs[0]
        ipv6_cidr_block_associations = vpc.get('Ipv6CidrBlockAssociationSet', [])
        ipv6_cidr_block = ipv6_cidr_block_associations[0]['Ipv6CidrBlock']
        print(f"Assigned IPv6 CIDR block {ipv6_cidr_block} to VPC {vpc_id}")
    else:
        ipv6_cidr_block = ipv6_cidr_block_associations[0]['Ipv6CidrBlock']
        print(f"VPC {vpc_id} already has IPv6 CIDR block {ipv6_cidr_block}")

    return ipv6_cidr_block

def assign_ipv6_cidr_to_subnets(ec2, vpc_id, ipv6_cidr_block):
    """
    Assign IPv6 CIDR blocks to all subnets within a VPC.
    
    Parameters:
        ec2: Boto3 EC2 client.
        vpc_id: ID of the VPC.
        ipv6_cidr_block: IPv6 CIDR block assigned to the VPC.
    """
    response = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    subnets = response.get('Subnets', [])
    
    # Calculate the subnet IPv6 CIDR blocks
    vpc_ipv6_network = IPv6Network(ipv6_cidr_block)
    subnet_size = vpc_ipv6_network.prefixlen + 8  # Assuming we want /64 subnets

    for index, subnet in enumerate(subnets):
        subnet_id = subnet['SubnetId']
        ipv6_cidr_block_associations = subnet.get('Ipv6CidrBlockAssociationSet', [])

        if not ipv6_cidr_block_associations:
            # Calculate the IPv6 CIDR block for this subnet
            subnet_ipv6_network = list(vpc_ipv6_network.subnets(new_prefix=subnet_size))[index]
            subnet_ipv6_cidr_block = str(subnet_ipv6_network)

            # Assign the IPv6 CIDR block to the subnet
            response = ec2.associate_subnet_cidr_block(SubnetId=subnet_id, Ipv6CidrBlock=subnet_ipv6_cidr_block)
            print(f"Assigned IPv6 CIDR block {subnet_ipv6_cidr_block} to Subnet {subnet_id}")
        else:
            print(f"Subnet {subnet_id} already has IPv6 CIDR blocks assigned.")

def create_and_attach_egress_only_igw(ec2, vpc_id):
    """
    Create an Egress-Only Internet Gateway if not already exists and attach it to private subnets.
    
    Parameters:
        ec2: Boto3 EC2 client.
        vpc_id: ID of the VPC.
    """
    # Check if an egress-only internet gateway already exists
    response = ec2.describe_egress_only_internet_gateways()
    egress_only_igws = response.get('EgressOnlyInternetGateways', [])
    
    egress_only_igw_id = None
    for igw in egress_only_igws:
        attachments = igw.get('Attachments', [])
        if any(attachment['VpcId'] == vpc_id for attachment in attachments):
            egress_only_igw_id = igw['EgressOnlyInternetGatewayId']
            break

    if not egress_only_igw_id:
        # Create an egress-only internet gateway
        response = ec2.create_egress_only_internet_gateway(VpcId=vpc_id)
        egress_only_igw_id = response['EgressOnlyInternetGateway']['EgressOnlyInternetGatewayId']
        print(f"Created Egress-Only Internet Gateway: {egress_only_igw_id}")
    else:
        print(f"Egress-Only Internet Gateway {egress_only_igw_id} already exists for VPC {vpc_id}")

    # Describe subnets in the VPC
    response = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    subnets = response.get('Subnets', [])
    
    private_subnets = []
    route_tables = []

    for subnet in subnets:
        subnet_id = subnet['SubnetId']
        route_table_response = ec2.describe_route_tables(Filters=[{'Name': 'association.subnet-id', 'Values': [subnet_id]}])
        if route_table_response['RouteTables']:
            route_table = route_table_response['RouteTables'][0]
            # Check if the subnet is private by looking for the absence of an internet gateway route
            igw_route = any(route.get('GatewayId', '').startswith('igw-') for route in route_table['Routes'])
            if not igw_route:
                private_subnets.append(subnet_id)
                route_tables.append(route_table['RouteTableId'])

    print(f"Identified private subnets in VPC {vpc_id}: {private_subnets}")

    # Attach the egress-only internet gateway to the private subnets' route tables
    for route_table_id in route_tables:
        try:
            ec2.create_route(RouteTableId=route_table_id, DestinationIpv6CidrBlock='::/0', EgressOnlyInternetGatewayId=egress_only_igw_id)
            print(f"Added route to route table {route_table_id} via egress-only internet gateway {egress_only_igw_id}")
        except Exception as e:
            print(f"Error adding route to route table {route_table_id}: {e}")

def lambda_handler(event, context):
    """
    Main Lambda handler function to enable IPv6 CIDR, assign to subnets,
    and attach egress-only internet gateway.
    
    Parameters:
        event: Event data.
        context: Runtime information.
    """
    session = boto3.Session()
    ec2_regions = ["us-east-1"]  # Specify the regions to process
    for region in ec2_regions:
        print(f"Processing region: {region}")
        ec2 = boto3.client('ec2', region_name=region)
        elbv2 = boto3.client('elbv2', region_name=region)
    
        response = ec2.describe_vpcs()
        vpcs = ["vpc-077e3872c3c662828"]  # List of VPC IDs to process
        vpcs = response.get('Vpcs', []) #uncomment it
        #vpcs = ["vpc-05999aa1be45ff7ac"] # comment it
        for vpc in vpcs:
            vpc_id = vpc['VpcId'] #uncommnt it
            #vpc_id = vpcs[0] #comment it
            print(f"Processing VPC {vpc_id} in region {region}")
    
            # Step 1: Enable IPv6 CIDR for the VPC if not already enabled
            ipv6_cidr_block = enable_ipv6_cidr_for_vpc(ec2, vpc_id)
    
            # Step 2: Assign IPv6 CIDR range to all subnets from the CIDR range of the VPC
            assign_ipv6_cidr_to_subnets(ec2, vpc_id, ipv6_cidr_block)
    
            # Step 3: Create egress-only internet gateway if not present and attach it to private subnets
            create_and_attach_egress_only_igw(ec2, vpc_id)
    
    print("Completed processing all regions.")

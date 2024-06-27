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

def assign_ipv6_addresses_to_instances(ec2_client, subnet_id):
    # Describe instances in the subnet
    response = ec2_client.describe_instances(
        Filters=[
            {'Name': 'subnet-id', 'Values': [subnet_id]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )

    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            for network_interface in instance['NetworkInterfaces']:
                if network_interface['SubnetId'] == subnet_id:
                    # Assign an IPv6 address to the network interface
                    ec2_client.assign_ipv6_addresses(
                        NetworkInterfaceId=network_interface['NetworkInterfaceId'],
                        Ipv6AddressCount=1
                    )
                    print(f"Assigned IPv6 address to instance {instance['InstanceId']}")

def lambda_handler(event, context):
    """
    Main Lambda handler function to enable IPv6 for private instances.
    
    Parameters:
        event: Event data.
        context: Runtime information.
    """
    session = boto3.Session()
    ec2 = session.client('ec2')
    
    # List all AWS regions
    regions_response = ec2.describe_regions()
    #regions = [region['RegionName'] for region in regions_response['Regions']] uncomment this line
    regions = ["us-east-1"] # comment this line

    for region in regions:
        print(f"Processing region: {region}")
        ec2_client = session.client('ec2', region_name=region)

        # List all VPCs in the region
        vpcs_response = ec2_client.describe_vpcs()
        for vpc in vpcs_response['Vpcs']:
            vpc_id = vpc['VpcId']
            if vpc_id in "vpc-08bd2cb875fa89b38":
                # Check if the VPC has IPv6 enabled
                if 'Ipv6CidrBlockAssociationSet' not in vpc or not vpc['Ipv6CidrBlockAssociationSet']:
                    print(f"vpc is not assigned IPv6 {vpc['VpcId']}")
                    continue  # Skip VPCs without IPv6 enabled
    
                # List all subnets in the VPC
                subnets_response = ec2_client.describe_subnets(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )
    
                for subnet in subnets_response['Subnets']:
                    subnet_id = subnet['SubnetId']
                    # Check if the subnet is private and has IPv6 enabled
                    route_table_response = ec2_client.describe_route_tables(
                    Filters=[{'Name': 'association.subnet-id', 'Values': [subnet_id]}]
                    )
                    if route_table_response['RouteTables']:
                        route_table = route_table_response['RouteTables'][0]
    
                        # Check if the subnet is private by looking for the absence of an internet gateway route
                        igw_route = any(route.get('GatewayId', '').startswith('igw-') for route in route_table['Routes'])
                        if igw_route :
                            continue
                        
                       
    
                        if 'Ipv6CidrBlockAssociationSet' not in subnet or not subnet['Ipv6CidrBlockAssociationSet']:
                            print(f"Subnet is not enabled for ipv6 {subnet_id}")
                            continue  # Skip subnets without IPv6 enabled
    
                        # Assign IPv6 addresses to instances in the subnet
                        assign_ipv6_addresses_to_instances(ec2_client, subnet_id)
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

def enable_ipv6_for_alb(elbv2, alb_arn):
    # Describe the load balancer to get current settings
    response = elbv2.describe_load_balancers(LoadBalancerArns=[alb_arn])
    load_balancer = response['LoadBalancers'][0]
    vpcids = ['vpc-077e3872c3c662828'] # comment ths line

    if load_balancer['VpcId'] in vpcids :#comment this line
        print(f"Processing ALB: {alb_arn}")

        # Check if IPv6 is already enabled
        if 'dualstack' in load_balancer['IpAddressType'].lower():
            print(f"IPv6 is already enabled for ALB: {alb_arn}")
            return
    
        # Enable IPv6
        elbv2.set_ip_address_type(
            LoadBalancerArn=alb_arn,
            IpAddressType='dualstack'
        )
        print(f"Enabled IPv6 for ALB: {alb_arn}")
        
        # Update ALB listeners to support IPv6
        update_alb_listeners_to_support_ipv6(elbv2, alb_arn)

def update_alb_listeners_to_support_ipv6(elbv2, alb_arn):
    # Get all listeners for the load balancer
    response = elbv2.describe_listeners(LoadBalancerArn=alb_arn)
    listeners = response['Listeners']

    for listener in listeners:
        listener_arn = listener['ListenerArn']
        port = listener['Port']
        protocol = listener['Protocol']
        default_actions = listener['DefaultActions']

        print(f"Updating listener {listener_arn} to support IPv6")

        # Modify listener to ensure IPv6 support
        elbv2.modify_listener(
            ListenerArn=listener_arn,
            Port=port,
            Protocol=protocol,
            DefaultActions=default_actions
        )
        print(f"Updated listener {listener_arn} to support IPv6")

def enable_ipv6_for_all_albs_in_region(region):
    session = boto3.Session()
    elbv2 = session.client('elbv2', region_name=region)

    # Describe all ALBs in the region
    response = elbv2.describe_load_balancers()
    albs = response['LoadBalancers']

    for alb in albs:
        alb_arn = alb['LoadBalancerArn']
        

        # Enable IPv6 for the ALB
        enable_ipv6_for_alb(elbv2, alb_arn)

        

def lambda_handler(event, context):
    """
    Main Lambda handler function to enable IPv6 for ELBs.
    
    Parameters:
        event: Event data.
        context: Runtime information.
    """
    session = boto3.Session()
    ec2 = session.client('ec2')

    # Get all available regions
    #ec2_regions = session.get_available_regions('ec2') uncomment this line
    ec2_regions = ["us-east-1"] #comment this line
    for region in ec2_regions:
        print(f"Processing region: {region}")
        enable_ipv6_for_all_albs_in_region(region)

    print("Completed updating ALBs to support IPv6 in all regions.")


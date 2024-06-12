from pathlib import Path

from aws_cdk import Duration, RemovalPolicy

# from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_elasticloadbalancingv2 as elbv2

# from aws_cdk import aws_route53 as route53
# from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct


class ChatBot(Construct):
    def __init__(self, scope: Construct, identifier: str, waf_acl: wafv2.CfnWebACL, is_production_env: bool, **kwargs) -> None:
        super().__init__(scope, identifier, **kwargs)
        self.id_ = identifier

        # Parameters
        domain_name = 'ranthebuilder-chatbot.com'

        # Build Docker image and push to ECR

        current = Path(__file__).parent
        docker_dir = str(Path(current / 'docker'))
        docker_image_asset = ecr_assets.DockerImageAsset(
            self,
            'ChatDockerImage',
            directory=docker_dir,  # Directory with Dockerfile
        )

        # Create a VPC
        vpc = ec2.Vpc(self, 'ChatVpc', max_azs=1)

        # Create an ECS cluster
        cluster = ecs.Cluster(self, 'ChatCluster', vpc=vpc)

        # Define an ECS task definition with a single container
        task_definition = ecs.FargateTaskDefinition(
            self,
            'ChatTaskDef',
            memory_limit_mib=512,
            cpu=256,
            capacity_provider_strategies=[
                ecs.CapacityProviderStrategy(capacity_provider='FARGATE_SPOT', weight=2),
                ecs.CapacityProviderStrategy(capacity_provider='FARGATE', weight=1),
            ],
        )

        # Add container to the task definition
        container = task_definition.add_container(
            'ChatBotContainer',
            image=ecs.ContainerImage.from_docker_image_asset(docker_image_asset),
            environment={'Chat_SERVER_HEADLESS': 'true'},
            logging=ecs.LogDrivers.aws_logs(stream_prefix='Chatbot'),
        )

        # Open the necessary port internally
        container.add_port_mappings(ecs.PortMapping(container_port=8501, protocol=ecs.Protocol.TCP))

        # Security group for the Fargate service
        security_group = ec2.SecurityGroup(self, 'ChatSecurityGroup', vpc=vpc)

        # Allow inbound traffic on ports 80 (HTTP) and 443 (HTTPS) from any IP
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), 'Allow HTTP traffic from the internet')
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), 'Allow HTTPS traffic from the internet')
        security_group.add_ingress_rule(ec2.Peer.any_ipv6(), ec2.Port.tcp(80), 'Allow HTTP traffic from the internet (IPv6)')
        security_group.add_ingress_rule(ec2.Peer.any_ipv6(), ec2.Port.tcp(443), 'Allow HTTPS traffic from the internet (IPv6)')

        # Create a certificate for the domain
        # certificate = acm.Certificate(self, 'ChatCertificate', domain_name=domain_name, validation=acm.CertificateValidation.from_dns())

        # Create a Fargate service and make it publicly accessible
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            'ChatFargateService',
            cluster=cluster,
            task_definition=task_definition,
            assign_public_ip=False,
            public_load_balancer=True,
            listener_port=443,
            # certificate=certificate,
            # domain_name=domain_name,
            # domain_zone=route53.HostedZone.from_lookup(self, 'BaseZone', domain_name=domain_name),
            desired_count=1,
            security_groups=[security_group],
        )

        # Associate the WAF web ACL with the ALB
        # wafv2.CfnWebACLAssociation(
        #    self, 'ChatWebACLAssociation', resource_arn=fargate_service.load_balancer.load_balancer_arn, web_acl_arn=waf_acl.attr_arn
        # )

        # Redirect HTTP to HTTPS
        http_listener = fargate_service.load_balancer.add_listener('HTTPListener', port=80, open=True)
        http_listener.add_action(
            'HTTPRedirect',
            action=elbv2.ListenerAction.redirect(protocol='HTTPS', port='443', path='/#{path}', query='#{query}', permanent=True),
        )

        # Limit scaling to one container
        fargate_service.service.auto_scale_task_count(min_capacity=1, max_capacity=1)

        # Ensure the load balancer is deleted when the stack is destroyed
        fargate_service.load_balancer.apply_removal_policy(RemovalPolicy.DESTROY)
        # fargate_service.target_group.configure_health_check(
        #    path='/', healthy_threshold_count=2, unhealthy_threshold_count=2, timeout=Duration.seconds(10)
        # )

        # Route 53 A record for the domain
        # route53.ARecord(
        #    self,
        #  'ChatAliasRecord',
        # zone=route53.HostedZone.from_lookup(self, 'HostedZone', domain_name=domain_name),
        # target=route53.RecordTarget.from_alias(targets.LoadBalancerTarget(fargate_service.load_balancer)),
        # record_name=domain_name,
        # )

"""
Test Data Generator Lambda
Generates realistic test incidents for system testing
Creates various incident scenarios with different severities
"""

import json
import boto3
import random
from datetime import datetime, timedelta
from typing import Dict, List

dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')

incidents_table = dynamodb.Table('ITOps-Incidents')

class TestDataGenerator:
    """Generates test incident data"""
    
    def __init__(self):
        self.generator_id = 'test-data-generator'
    
    # Incident templates
    INCIDENT_TEMPLATES = {
        'critical': [
            {
                'title': 'Complete Database Outage',
                'description': 'Primary RDS instance is completely unresponsive. All database connections timing out. Total system outage affecting all users.',
                'affected_services': ['RDS', 'EC2', 'Lambda', 'API-Gateway'],
                'detected_by': 'PagerDuty'
            },
            {
                'title': 'DDoS Attack Detected',
                'description': 'Massive spike in traffic from suspicious sources. Application servers overwhelmed. Service degraded for all customers.',
                'affected_services': ['CloudFront', 'ALB', 'WAF', 'EC2'],
                'detected_by': 'AWS Shield'
            },
            {
                'title': 'Data Loss - S3 Bucket Deleted',
                'description': 'Critical S3 bucket accidentally deleted. Customer data potentially lost. Immediate recovery required.',
                'affected_services': ['S3', 'Lambda', 'CloudFront'],
                'detected_by': 'Manual'
            },
            {
                'title': 'Security Breach - Unauthorized Access',
                'description': 'Suspicious activity detected in production account. Potential security breach. Multiple failed login attempts from unknown IPs.',
                'affected_services': ['IAM', 'CloudTrail', 'GuardDuty'],
                'detected_by': 'GuardDuty'
            }
        ],
        'high': [
            {
                'title': 'High Memory Usage on Lambda',
                'description': 'Lambda function consuming 95% memory consistently. Causing throttling and timeout errors. Multiple users affected.',
                'affected_services': ['Lambda', 'API-Gateway', 'DynamoDB'],
                'detected_by': 'CloudWatch'
            },
            {
                'title': 'API Gateway 504 Timeouts',
                'description': 'API Gateway experiencing high rate of 504 timeout errors. Affecting 30% of requests. User complaints increasing.',
                'affected_services': ['API-Gateway', 'Lambda', 'VPC'],
                'detected_by': 'CloudWatch'
            },
            {
                'title': 'DynamoDB Throttling',
                'description': 'DynamoDB table hitting throughput limits. Read/write requests being throttled. Application performance degraded.',
                'affected_services': ['DynamoDB', 'Lambda'],
                'detected_by': 'CloudWatch'
            },
            {
                'title': 'EC2 Instance High CPU',
                'description': 'Production EC2 instances running at 90%+ CPU for extended period. Response times degraded. Auto-scaling not responding.',
                'affected_services': ['EC2', 'Auto Scaling', 'ALB'],
                'detected_by': 'CloudWatch'
            },
            {
                'title': 'S3 Bucket Permission Error',
                'description': 'Critical S3 bucket suddenly returning 403 errors. Bucket policy may have been modified. Affecting file uploads.',
                'affected_services': ['S3', 'Lambda', 'CloudFront'],
                'detected_by': 'Application Logs'
            }
        ],
        'medium': [
            {
                'title': 'Intermittent API Timeouts',
                'description': 'API experiencing intermittent timeout errors. Affecting approximately 10% of requests. Pattern unclear.',
                'affected_services': ['API-Gateway', 'Lambda'],
                'detected_by': 'CloudWatch'
            },
            {
                'title': 'CloudWatch Logs Storage Increase',
                'description': 'CloudWatch Logs storage increased by 200% over baseline. Potential logging misconfiguration.',
                'affected_services': ['CloudWatch', 'Lambda'],
                'detected_by': 'Cost Monitoring'
            },
            {
                'title': 'Slow Database Queries',
                'description': 'Database query performance degraded. Average query time increased from 50ms to 300ms. No obvious bottleneck.',
                'affected_services': ['RDS', 'Lambda'],
                'detected_by': 'Performance Monitor'
            },
            {
                'title': 'Certificate Expiring Soon',
                'description': 'SSL certificate for production domain expiring in 7 days. Renewal process needs to be initiated.',
                'affected_services': ['ACM', 'CloudFront', 'ALB'],
                'detected_by': 'Certificate Monitor'
            },
            {
                'title': 'Lambda Cold Start Issues',
                'description': 'Lambda functions experiencing increased cold start times. First invocations taking 3-5 seconds.',
                'affected_services': ['Lambda', 'API-Gateway'],
                'detected_by': 'Performance Monitor'
            }
        ],
        'low': [
            {
                'title': 'Minor UI Rendering Glitch',
                'description': 'Button alignment issue on dashboard. Cosmetic only, no functional impact. Reported by single user.',
                'affected_services': ['Frontend', 'S3'],
                'detected_by': 'User Report'
            },
            {
                'title': 'Deprecated API Warning',
                'description': 'Using deprecated AWS SDK version. No immediate impact but should be updated for future compatibility.',
                'affected_services': ['Lambda'],
                'detected_by': 'Code Review'
            },
            {
                'title': 'Unused Resources Detected',
                'description': 'Several unused EC2 instances and old snapshots identified. Cost optimization opportunity.',
                'affected_services': ['EC2', 'EBS'],
                'detected_by': 'Cost Explorer'
            },
            {
                'title': 'Documentation Outdated',
                'description': 'API documentation does not reflect recent changes. No operational impact but needs updating.',
                'affected_services': ['Documentation'],
                'detected_by': 'Manual Review'
            }
        ]
    }
    
    def generate_incident(self, severity: str = None, trigger_workflow: bool = True) -> Dict:
        """
        Generate a single test incident
        
        Args:
            severity: Specific severity level (critical, high, medium, low) or random
            trigger_workflow: Whether to trigger Step Functions workflow
        
        Returns:
            Generated incident data
        """
        
        # Choose severity
        if not severity:
            severity = random.choices(
                ['critical', 'high', 'medium', 'low'],
                weights=[0.1, 0.2, 0.4, 0.3]
            )[0]
        
        # Select random template
        templates = self.INCIDENT_TEMPLATES.get(severity, self.INCIDENT_TEMPLATES['medium'])
        template = random.choice(templates)
        
        # Generate incident
        timestamp = int(datetime.now().timestamp())
        incident_id = f"INC-TEST-{severity.upper()}-{timestamp}"
        
        incident = {
            'incident_id': incident_id,
            'created_at': timestamp,
            'title': template['title'],
            'description': template['description'],
            'severity': severity,
            'status': 'open',
            'affected_services': template['affected_services'],
            'detected_by': template['detected_by'],
            'environment': 'test',
            'region': 'us-east-1',
            'tags': ['test', 'generated', severity],
            'timeline': [],
            'metrics': self._generate_metrics(severity)
        }
        
        # Save to DynamoDB
        self._save_incident(incident)
        
        # Trigger workflow if requested
        workflow_result = None
        if trigger_workflow:
            workflow_result = self._trigger_workflow(incident_id, incident)
        
        return {
            'incident_id': incident_id,
            'severity': severity,
            'title': template['title'],
            'created': True,
            'workflow_triggered': trigger_workflow,
            'workflow_execution': workflow_result
        }
    
    def generate_batch(self, count: int = 10, trigger_workflow: bool = False) -> Dict:
        """
        Generate multiple test incidents
        
        Args:
            count: Number of incidents to generate
            trigger_workflow: Whether to trigger workflows
        
        Returns:
            Batch generation results
        """
        
        results = {
            'total': count,
            'generated': [],
            'failed': [],
            'by_severity': {
                'critical': 0,
                'high': 0,
                'medium': 0,
                'low': 0
            }
        }
        
        for i in range(count):
            try:
                incident = self.generate_incident(trigger_workflow=trigger_workflow)
                results['generated'].append(incident)
                results['by_severity'][incident['severity']] += 1
            except Exception as e:
                results['failed'].append({
                    'index': i,
                    'error': str(e)
                })
        
        return results
    
    def generate_scenario(self, scenario_name: str, trigger_workflow: bool = True) -> Dict:
        """
        Generate specific test scenario
        
        Args:
            scenario_name: Name of scenario to generate
            trigger_workflow: Whether to trigger workflows
        
        Returns:
            Scenario generation results
        """
        
        scenarios = {
            'cascade_failure': self._scenario_cascade_failure,
            'gradual_degradation': self._scenario_gradual_degradation,
            'security_event': self._scenario_security_event,
            'capacity_issue': self._scenario_capacity_issue,
            'network_problem': self._scenario_network_problem
        }
        
        if scenario_name not in scenarios:
            return {
                'error': f"Unknown scenario: {scenario_name}",
                'available_scenarios': list(scenarios.keys())
            }
        
        return scenarios[scenario_name](trigger_workflow)
    
    def _scenario_cascade_failure(self, trigger_workflow: bool) -> Dict:
        """Simulate cascading failure scenario"""
        
        incidents = []
        
        # Start with database issue
        incidents.append(self.generate_incident('high', trigger_workflow))
        
        # Followed by dependent service failures
        for severity in ['medium', 'medium', 'low']:
            incidents.append(self.generate_incident(severity, trigger_workflow))
        
        return {
            'scenario': 'cascade_failure',
            'description': 'Cascading failure starting from database',
            'incidents': incidents
        }
    
    def _scenario_gradual_degradation(self, trigger_workflow: bool) -> Dict:
        """Simulate gradual performance degradation"""
        
        incidents = [
            self.generate_incident('low', trigger_workflow),
            self.generate_incident('medium', trigger_workflow),
            self.generate_incident('high', trigger_workflow)
        ]
        
        return {
            'scenario': 'gradual_degradation',
            'description': 'Performance gradually degrading',
            'incidents': incidents
        }
    
    def _scenario_security_event(self, trigger_workflow: bool) -> Dict:
        """Simulate security incident"""
        
        return {
            'scenario': 'security_event',
            'description': 'Security breach detected',
            'incidents': [self.generate_incident('critical', trigger_workflow)]
        }
    
    def _scenario_capacity_issue(self, trigger_workflow: bool) -> Dict:
        """Simulate capacity/scaling issue"""
        
        incidents = [
            self.generate_incident('medium', trigger_workflow),
            self.generate_incident('high', trigger_workflow)
        ]
        
        return {
            'scenario': 'capacity_issue',
            'description': 'System reaching capacity limits',
            'incidents': incidents
        }
    
    def _scenario_network_problem(self, trigger_workflow: bool) -> Dict:
        """Simulate network connectivity issue"""
        
        return {
            'scenario': 'network_problem',
            'description': 'Network connectivity degraded',
            'incidents': [self.generate_incident('high', trigger_workflow)]
        }
    
    def _generate_metrics(self, severity: str) -> Dict:
        """Generate realistic metrics based on severity"""
        
        base_metrics = {
            'critical': {'cpu': 95, 'memory': 98, 'error_rate': 45},
            'high': {'cpu': 85, 'memory': 90, 'error_rate': 25},
            'medium': {'cpu': 70, 'memory': 75, 'error_rate': 10},
            'low': {'cpu': 50, 'memory': 60, 'error_rate': 2}
        }
        
        metrics = base_metrics.get(severity, base_metrics['medium'])
        
        return {
            'cpu_utilization': metrics['cpu'] + random.randint(-5, 5),
            'memory_utilization': metrics['memory'] + random.randint(-5, 5),
            'error_rate': metrics['error_rate'] + random.uniform(-2, 2),
            'request_count': random.randint(1000, 10000),
            'response_time_ms': random.randint(100, 3000)
        }
    
    def _save_incident(self, incident: Dict):
        """Save incident to DynamoDB"""
        
        try:
            incidents_table.put_item(Item=incident)
            print(f"Saved test incident: {incident['incident_id']}")
        except Exception as e:
            print(f"Error saving incident: {e}")
            raise
    
    def _trigger_workflow(self, incident_id: str, incident: Dict) -> Dict:
        """Trigger Step Functions workflow"""
        
        try:
            state_machine_arn = 'arn:aws:states:us-east-1:005185643085:stateMachine:ITOps-IncidentWorkflow'
            
            execution = stepfunctions.start_execution(
                stateMachineArn=state_machine_arn,
                name=f"{incident_id}_{int(datetime.now().timestamp())}",
                input=json.dumps({
                    'incident_id': incident_id,
                    'incident': incident
                })
            )
            
            return {
                'triggered': True,
                'execution_arn': execution['executionArn']
            }
        
        except Exception as e:
            print(f"Error triggering workflow: {e}")
            return {
                'triggered': False,
                'error': str(e)
            }


def lambda_handler(event, context):
    """
    Lambda handler for test data generation
    
    Event formats:
    
    1. Generate single incident:
    {
        "action": "generate",
        "severity": "critical|high|medium|low",
        "trigger_workflow": true
    }
    
    2. Generate batch:
    {
        "action": "batch",
        "count": 10,
        "trigger_workflow": false
    }
    
    3. Generate scenario:
    {
        "action": "scenario",
        "scenario": "cascade_failure|gradual_degradation|security_event|capacity_issue|network_problem",
        "trigger_workflow": true
    }
    """
    
    print(f"Test Data Generator received: {json.dumps(event)}")
    
    generator = TestDataGenerator()
    
    try:
        action = event.get('action', 'generate')
        
        if action == 'generate':
            severity = event.get('severity')
            trigger_workflow = event.get('trigger_workflow', True)
            
            result = generator.generate_incident(severity, trigger_workflow)
            
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        
        elif action == 'batch':
            count = event.get('count', 10)
            trigger_workflow = event.get('trigger_workflow', False)
            
            result = generator.generate_batch(count, trigger_workflow)
            
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        
        elif action == 'scenario':
            scenario = event.get('scenario', 'cascade_failure')
            trigger_workflow = event.get('trigger_workflow', True)
            
            result = generator.generate_scenario(scenario, trigger_workflow)
            
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': f"Invalid action: {action}",
                    'valid_actions': ['generate', 'batch', 'scenario']
                })
            }
    
    except Exception as e:
        print(f"Error in test data generator: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
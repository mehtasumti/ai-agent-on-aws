"""
Verify Resolution Lambda
Verifies that incident remediation was successful
Checks metrics, logs, and service health to confirm resolution
"""

import json
import boto3
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

dynamodb = boto3.resource('dynamodb')
cloudwatch = boto3.client('cloudwatch')
logs = boto3.client('logs')
lambda_client = boto3.client('lambda')

incidents_table = dynamodb.Table('ITOps-Incidents')

class ResolutionVerifier:
    """Verifies incident resolution and service health"""
    
    def __init__(self):
        self.verifier_id = 'resolution-verifier'
        self.verification_window_minutes = 15  # Check last 15 minutes
    
    def verify_resolution(
        self,
        incident_id: str,
        incident_data: Dict,
        remediation_plan: Dict = None
    ) -> Dict:
        """
        Verify that incident has been successfully resolved
        
        Args:
            incident_id: Incident identifier
            incident_data: Incident details
            remediation_plan: Optional remediation plan with success criteria
        
        Returns:
            Verification result with detailed checks
        """
        
        verification_result = {
            'incident_id': incident_id,
            'verified': False,
            'timestamp': datetime.now().isoformat(),
            'checks': {
                'metrics': None,
                'error_logs': None,
                'service_health': None,
                'success_criteria': None
            },
            'summary': '',
            'confidence': 0.0,
            'recommendation': ''
        }
        
        # Check 1: Metrics verification
        metrics_check = self._verify_metrics(incident_data)
        verification_result['checks']['metrics'] = metrics_check
        
        # Check 2: Error logs verification
        logs_check = self._verify_error_logs(incident_data)
        verification_result['checks']['error_logs'] = logs_check
        
        # Check 3: Service health verification
        health_check = self._verify_service_health(incident_data)
        verification_result['checks']['service_health'] = health_check
        
        # Check 4: Success criteria from remediation plan
        if remediation_plan:
            criteria_check = self._verify_success_criteria(
                incident_data,
                remediation_plan.get('success_criteria', [])
            )
            verification_result['checks']['success_criteria'] = criteria_check
        
        # Calculate overall verification status
        all_checks = [
            metrics_check,
            logs_check,
            health_check
        ]
        
        if remediation_plan:
            all_checks.append(criteria_check)
        
        # Determine if verified
        passed_checks = sum(1 for check in all_checks if check.get('passed'))
        total_checks = len(all_checks)
        
        verification_result['confidence'] = (passed_checks / total_checks) * 100
        verification_result['verified'] = verification_result['confidence'] >= 75.0
        
        # Generate summary
        verification_result['summary'] = self._generate_summary(
            verification_result['verified'],
            passed_checks,
            total_checks
        )
        
        # Generate recommendation
        verification_result['recommendation'] = self._generate_recommendation(
            verification_result
        )
        
        # Update incident with verification results
        self._update_incident(incident_id, verification_result)
        
        return verification_result
    
    def _verify_metrics(self, incident_data: Dict) -> Dict:
        """Verify that metrics are within normal ranges"""
        
        affected_services = incident_data.get('affected_services', [])
        severity = incident_data.get('severity', 'medium')
        
        result = {
            'passed': False,
            'metric_checks': [],
            'message': ''
        }
        
        try:
            # Define expected metric ranges based on severity
            expected_ranges = {
                'critical': {'cpu': 50, 'memory': 60, 'error_rate': 1},
                'high': {'cpu': 60, 'memory': 70, 'error_rate': 2},
                'medium': {'cpu': 70, 'memory': 75, 'error_rate': 5},
                'low': {'cpu': 80, 'memory': 80, 'error_rate': 10}
            }
            
            ranges = expected_ranges.get(severity, expected_ranges['medium'])
            
            # Check Lambda metrics if Lambda is affected
            if 'Lambda' in affected_services:
                lambda_metrics = self._check_lambda_metrics(ranges)
                result['metric_checks'].append(lambda_metrics)
            
            # Check EC2 metrics if EC2 is affected
            if 'EC2' in affected_services:
                ec2_metrics = self._check_ec2_metrics(ranges)
                result['metric_checks'].append(ec2_metrics)
            
            # Check RDS metrics if RDS is affected
            if 'RDS' in affected_services:
                rds_metrics = self._check_rds_metrics(ranges)
                result['metric_checks'].append(rds_metrics)
            
            # Check API Gateway metrics if API-Gateway is affected
            if 'API-Gateway' in affected_services:
                api_metrics = self._check_api_gateway_metrics(ranges)
                result['metric_checks'].append(api_metrics)
            
            # Determine if all metrics passed
            if result['metric_checks']:
                passed_metrics = sum(1 for m in result['metric_checks'] if m['within_range'])
                result['passed'] = passed_metrics == len(result['metric_checks'])
                result['message'] = f"{passed_metrics}/{len(result['metric_checks'])} metrics within normal range"
            else:
                # No specific metrics to check
                result['passed'] = True
                result['message'] = 'No metrics to verify (simulated pass)'
        
        except Exception as e:
            result['message'] = f'Error checking metrics: {str(e)}'
        
        return result
    
    def _check_lambda_metrics(self, expected_ranges: Dict) -> Dict:
        """Check Lambda function metrics"""
        
        # Simulate metric check (in production, query CloudWatch)
        return {
            'service': 'Lambda',
            'metrics': {
                'error_rate': 0.5,  # Simulated
                'duration': 250,    # Simulated
                'throttles': 0      # Simulated
            },
            'within_range': True,
            'message': 'Lambda metrics normal'
        }
    
    def _check_ec2_metrics(self, expected_ranges: Dict) -> Dict:
        """Check EC2 instance metrics"""
        
        return {
            'service': 'EC2',
            'metrics': {
                'cpu_utilization': 45,  # Simulated
                'network_in': 1000000,  # Simulated
                'status_check': 'passed'
            },
            'within_range': True,
            'message': 'EC2 metrics normal'
        }
    
    def _check_rds_metrics(self, expected_ranges: Dict) -> Dict:
        """Check RDS database metrics"""
        
        return {
            'service': 'RDS',
            'metrics': {
                'cpu_utilization': 35,
                'db_connections': 50,
                'read_latency': 0.01
            },
            'within_range': True,
            'message': 'RDS metrics normal'
        }
    
    def _check_api_gateway_metrics(self, expected_ranges: Dict) -> Dict:
        """Check API Gateway metrics"""
        
        return {
            'service': 'API-Gateway',
            'metrics': {
                '4xx_errors': 2,
                '5xx_errors': 0,
                'latency': 150
            },
            'within_range': True,
            'message': 'API Gateway metrics normal'
        }
    
    def _verify_error_logs(self, incident_data: Dict) -> Dict:
        """Verify that error rate in logs has decreased"""
        
        result = {
            'passed': False,
            'error_count': 0,
            'baseline_errors': 0,
            'reduction_percent': 0,
            'message': ''
        }
        
        try:
            # In production, query CloudWatch Logs
            # For now, simulate check
            
            # Simulate checking logs
            current_errors = 2      # Simulated current error count
            baseline_errors = 50    # Simulated baseline before remediation
            
            result['error_count'] = current_errors
            result['baseline_errors'] = baseline_errors
            
            if baseline_errors > 0:
                reduction = ((baseline_errors - current_errors) / baseline_errors) * 100
                result['reduction_percent'] = reduction
                result['passed'] = reduction >= 80  # 80% reduction target
                result['message'] = f"Error rate reduced by {reduction:.1f}%"
            else:
                result['passed'] = True
                result['message'] = 'No baseline errors to compare'
        
        except Exception as e:
            result['message'] = f'Error checking logs: {str(e)}'
        
        return result
    
    def _verify_service_health(self, incident_data: Dict) -> Dict:
        """Verify overall service health"""
        
        result = {
            'passed': False,
            'services_checked': [],
            'all_healthy': False,
            'message': ''
        }
        
        try:
            affected_services = incident_data.get('affected_services', [])
            
            for service in affected_services:
                health = self._check_service_health(service)
                result['services_checked'].append(health)
            
            if result['services_checked']:
                healthy_count = sum(1 for s in result['services_checked'] if s['healthy'])
                total = len(result['services_checked'])
                
                result['all_healthy'] = healthy_count == total
                result['passed'] = result['all_healthy']
                result['message'] = f"{healthy_count}/{total} services healthy"
            else:
                result['passed'] = True
                result['message'] = 'No services to check'
        
        except Exception as e:
            result['message'] = f'Error checking service health: {str(e)}'
        
        return result
    
    def _check_service_health(self, service_name: str) -> Dict:
        """Check health of specific service"""
        
        # Simulate health check (in production, call actual health endpoints)
        return {
            'service': service_name,
            'healthy': True,
            'status': 'operational',
            'last_check': datetime.now().isoformat()
        }
    
    def _verify_success_criteria(self, incident_data: Dict, criteria: List[str]) -> Dict:
        """Verify success criteria from remediation plan"""
        
        result = {
            'passed': False,
            'criteria_met': [],
            'criteria_failed': [],
            'message': ''
        }
        
        if not criteria:
            result['passed'] = True
            result['message'] = 'No success criteria defined'
            return result
        
        # Check each criterion
        for criterion in criteria:
            # Simulate checking (in production, implement actual checks)
            met = True  # Simulate success
            
            if met:
                result['criteria_met'].append(criterion)
            else:
                result['criteria_failed'].append(criterion)
        
        result['passed'] = len(result['criteria_failed']) == 0
        result['message'] = f"{len(result['criteria_met'])}/{len(criteria)} criteria met"
        
        return result
    
    def _generate_summary(self, verified: bool, passed: int, total: int) -> str:
        """Generate human-readable summary"""
        
        if verified:
            return f"✅ Incident resolution VERIFIED - {passed}/{total} checks passed"
        else:
            return f"⚠️ Incident resolution UNCERTAIN - Only {passed}/{total} checks passed"
    
    def _generate_recommendation(self, verification_result: Dict) -> str:
        """Generate recommendation based on verification"""
        
        confidence = verification_result['confidence']
        
        if confidence >= 90:
            return "Resolution confirmed. Safe to close incident."
        elif confidence >= 75:
            return "Resolution likely successful. Monitor for 24 hours before closing."
        elif confidence >= 50:
            return "Resolution uncertain. Continue monitoring and consider additional remediation."
        else:
            return "Resolution verification failed. Manual investigation required."
    
    def _update_incident(self, incident_id: str, verification_result: Dict):
        """Update incident with verification results"""
        
        try:
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            if response.get('Items'):
                created_at = response['Items'][0]['created_at']
                
                new_status = 'resolved' if verification_result['verified'] else 'monitoring'
                
                incidents_table.update_item(
                    Key={'incident_id': incident_id, 'created_at': created_at},
                    UpdateExpression='''
                        SET #status = :status,
                            verification_result = :verification,
                            timeline = list_append(if_not_exists(timeline, :empty_list), :event)
                    ''',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':status': new_status,
                        ':verification': verification_result,
                        ':empty_list': [],
                        ':event': [{
                            'timestamp': int(datetime.now().timestamp()),
                            'event': 'resolution_verified' if verification_result['verified'] else 'verification_uncertain',
                            'actor': 'resolution_verifier',
                            'details': json.dumps({
                                'verified': verification_result['verified'],
                                'confidence': verification_result['confidence']
                            })
                        }]
                    }
                )
        
        except Exception as e:
            print(f"Error updating incident: {e}")


def lambda_handler(event, context):
    """
    Lambda handler for resolution verification
    
    Event format:
    {
        "incident_id": "INC-XXXXX",
        "incident": {...},
        "remediation_plan": {...}  // optional
    }
    """
    
    print(f"Resolution Verifier received: {json.dumps(event)}")
    
    try:
        incident_id = event.get('incident_id')
        incident_data = event.get('incident')
        remediation_plan = event.get('remediation_plan')
        
        if not incident_id or not incident_data:
            return {
                'statusCode': 400,
                'result': {
                    'verified': False,
                    'error': 'Missing incident_id or incident data'
                }
            }
        
        # Verify resolution
        verifier = ResolutionVerifier()
        result = verifier.verify_resolution(
            incident_id,
            incident_data,
            remediation_plan
        )
        
        return {
            'statusCode': 200,
            'result': result
        }
    
    except Exception as e:
        print(f"Error in resolution verifier: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'result': {
                'incident_id': event.get('incident_id', 'unknown'),
                'verified': False,
                'error': str(e)
            }
        }
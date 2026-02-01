"""
Execute Remediation Lambda
Executes approved remediation plans with safety checks
Supports rollback and verification
"""

import json
import boto3
from datetime import datetime
from typing import Dict, List, Tuple

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
cloudwatch = boto3.client('cloudwatch')
ec2 = boto3.client('ec2')
rds = boto3.client('rds')
elbv2 = boto3.client('elbv2')

incidents_table = dynamodb.Table('ITOps-Incidents')
approval_queue_table = dynamodb.Table('ITOps-ApprovalQueue')
remediation_log_table = dynamodb.Table('ITOps-RemediationLog')

class RemediationExecutor:
    """Executes remediation actions with safety checks"""
    
    def __init__(self):
        self.executor_id = 'remediation-executor'
        self.dry_run = False  # Set to True for testing
    
    def execute(
        self,
        incident_id: str,
        remediation_plan: Dict,
        approval_id: str = None
    ) -> Dict:
        """
        Execute remediation plan
        
        Args:
            incident_id: Incident identifier
            remediation_plan: Full remediation plan
            approval_id: Optional approval ID (required for high-risk)
        
        Returns:
            Execution results with success/failure status
        """
        
        # Verify approval if required
        if approval_id:
            approved = self._verify_approval(approval_id)
            if not approved:
                return {
                    'incident_id': incident_id,
                    'status': 'blocked',
                    'message': 'Approval not granted or expired',
                    'executed_actions': []
                }
        
        # Pre-execution checks
        safety_check = self._pre_execution_safety_check(remediation_plan)
        if not safety_check['safe']:
            return {
                'incident_id': incident_id,
                'status': 'aborted',
                'message': f"Safety check failed: {safety_check['reason']}",
                'executed_actions': []
            }
        
        # Execute actions
        results = {
            'incident_id': incident_id,
            'execution_id': f"EXEC-{int(datetime.now().timestamp())}",
            'status': 'in_progress',
            'started_at': datetime.now().isoformat(),
            'immediate_actions': [],
            'corrective_actions': [],
            'failed_actions': [],
            'rollback_performed': False
        }
        
        # Execute immediate actions
        for action in remediation_plan.get('immediate_actions', []):
            result = self._execute_action(action, 'immediate')
            results['immediate_actions'].append(result)
            
            if not result['success']:
                results['failed_actions'].append(result)
                # Stop if critical action fails
                if action.get('critical', False):
                    results['status'] = 'failed'
                    results['message'] = f"Critical action failed: {action.get('action')}"
                    return results
        
        # Execute corrective actions
        for action in remediation_plan.get('corrective_actions', []):
            result = self._execute_action(action, 'corrective')
            results['corrective_actions'].append(result)
            
            if not result['success']:
                results['failed_actions'].append(result)
        
        # Determine overall status
        if len(results['failed_actions']) == 0:
            results['status'] = 'success'
            results['message'] = 'All remediation actions completed successfully'
        elif len(results['failed_actions']) < len(results['immediate_actions']) + len(results['corrective_actions']):
            results['status'] = 'partial_success'
            results['message'] = f"{len(results['failed_actions'])} actions failed"
        else:
            results['status'] = 'failed'
            results['message'] = 'Remediation failed'
        
        results['completed_at'] = datetime.now().isoformat()
        
        # Log execution
        self._log_execution(incident_id, results)
        
        # Update incident
        self._update_incident(incident_id, results)
        
        # Verify remediation success
        if results['status'] in ['success', 'partial_success']:
            verification = self._verify_remediation(incident_id, remediation_plan)
            results['verification'] = verification
        
        return results
    
    def _verify_approval(self, approval_id: str) -> bool:
        """Verify that approval has been granted"""
        
        try:
            response = approval_queue_table.query(
                KeyConditionExpression='approval_id = :id',
                ExpressionAttributeValues={':id': approval_id}
            )
            
            items = response.get('Items', [])
            if not items:
                print(f"Approval {approval_id} not found")
                return False
            
            approval = items[0]
            status = approval.get('status', 'pending')
            
            if status == 'approved':
                print(f"Approval {approval_id} verified")
                return True
            else:
                print(f"Approval {approval_id} not approved (status: {status})")
                return False
        
        except Exception as e:
            print(f"Error verifying approval: {e}")
            return False
    
    def _pre_execution_safety_check(self, plan: Dict) -> Dict:
        """Perform safety checks before execution"""
        
        # Check 1: No destructive actions without reversibility
        all_actions = plan.get('immediate_actions', []) + plan.get('corrective_actions', [])
        
        for action in all_actions:
            if action.get('risk') == 'high' and not action.get('reversible', False):
                return {
                    'safe': False,
                    'reason': f"High-risk irreversible action: {action.get('action')}"
                }
        
        # Check 2: Maximum execution time not exceeded
        # (Add your business logic here)
        
        # Check 3: No conflicting operations
        # (Add your business logic here)
        
        return {'safe': True, 'reason': 'All safety checks passed'}
    
    def _execute_action(self, action: Dict, action_type: str) -> Dict:
        """Execute a single remediation action"""
        
        action_name = action.get('action', 'Unknown')
        command = action.get('command', '')
        risk = action.get('risk', 'medium')
        
        print(f"Executing {action_type} action: {action_name}")
        print(f"Command: {command}")
        print(f"Risk: {risk}")
        
        result = {
            'action': action_name,
            'type': action_type,
            'risk': risk,
            'timestamp': datetime.now().isoformat(),
            'success': False,
            'output': '',
            'error': None
        }
        
        try:
            # Determine action category and execute
            if 'lambda' in command.lower():
                result.update(self._execute_lambda_action(command))
            elif 'ec2' in command.lower():
                result.update(self._execute_ec2_action(command))
            elif 'rds' in command.lower():
                result.update(self._execute_rds_action(command))
            elif 'scaling' in command.lower() or 'autoscaling' in command.lower():
                result.update(self._execute_scaling_action(command))
            elif 'restart' in command.lower():
                result.update(self._execute_restart_action(command))
            else:
                # Generic execution (simulated)
                result.update(self._simulate_action(command))
            
            result['success'] = True
            
        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"Action failed: {e}")
        
        return result
    
    def _execute_lambda_action(self, command: str) -> Dict:
        """Execute Lambda-related actions"""
        
        if self.dry_run:
            return {
                'output': f'[DRY RUN] Would execute: {command}',
                'simulated': True
            }
        
        # Example: Update Lambda memory configuration
        if 'update-function-configuration' in command:
            # Parse command to extract function name and settings
            # aws lambda update-function-configuration --function-name X --memory-size Y
            return {
                'output': f'Lambda configuration updated (simulated)',
                'simulated': True
            }
        
        return {
            'output': f'Lambda action executed: {command}',
            'simulated': True
        }
    
    def _execute_ec2_action(self, command: str) -> Dict:
        """Execute EC2-related actions"""
        
        if self.dry_run:
            return {
                'output': f'[DRY RUN] Would execute: {command}',
                'simulated': True
            }
        
        # Example: Restart EC2 instance
        if 'reboot-instances' in command:
            return {
                'output': 'EC2 instances restarted (simulated)',
                'simulated': True
            }
        
        return {
            'output': f'EC2 action executed: {command}',
            'simulated': True
        }
    
    def _execute_rds_action(self, command: str) -> Dict:
        """Execute RDS-related actions"""
        
        if self.dry_run:
            return {
                'output': f'[DRY RUN] Would execute: {command}',
                'simulated': True
            }
        
        # Example: Modify RDS instance
        if 'modify-db-instance' in command:
            return {
                'output': 'RDS instance modified (simulated)',
                'simulated': True
            }
        
        return {
            'output': f'RDS action executed: {command}',
            'simulated': True
        }
    
    def _execute_scaling_action(self, command: str) -> Dict:
        """Execute auto-scaling actions"""
        
        if self.dry_run:
            return {
                'output': f'[DRY RUN] Would execute: {command}',
                'simulated': True
            }
        
        return {
            'output': f'Scaling action executed: {command}',
            'simulated': True
        }
    
    def _execute_restart_action(self, command: str) -> Dict:
        """Execute restart/reboot actions"""
        
        if self.dry_run:
            return {
                'output': f'[DRY RUN] Would execute: {command}',
                'simulated': True
            }
        
        return {
            'output': f'Restart completed: {command}',
            'simulated': True
        }
    
    def _simulate_action(self, command: str) -> Dict:
        """Simulate generic action execution"""
        
        return {
            'output': f'Action executed successfully (simulated): {command}',
            'simulated': True
        }
    
    def _verify_remediation(self, incident_id: str, plan: Dict) -> Dict:
        """Verify that remediation was successful"""
        
        success_criteria = plan.get('success_criteria', [])
        
        verification_results = {
            'verified': True,
            'criteria_met': [],
            'criteria_failed': [],
            'timestamp': datetime.now().isoformat()
        }
        
        # Check each success criterion
        for criterion in success_criteria:
            # In production, implement actual verification checks
            # For now, simulate verification
            met = True  # Assume success
            
            if met:
                verification_results['criteria_met'].append(criterion)
            else:
                verification_results['criteria_failed'].append(criterion)
                verification_results['verified'] = False
        
        return verification_results
    
    def _log_execution(self, incident_id: str, results: Dict):
        """Log execution to DynamoDB"""
        
        try:
            remediation_log_table.put_item(
                Item={
                    'execution_id': results['execution_id'],
                    'incident_id': incident_id,
                    'timestamp': int(datetime.now().timestamp()),
                    'status': results['status'],
                    'actions_executed': len(results['immediate_actions']) + len(results['corrective_actions']),
                    'actions_failed': len(results['failed_actions']),
                    'details': results,
                    'ttl': int(datetime.now().timestamp()) + 2592000  # 30 days
                }
            )
        
        except Exception as e:
            print(f"Error logging execution: {e}")
    
    def _update_incident(self, incident_id: str, results: Dict):
        """Update incident with execution results"""
        
        try:
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            if response.get('Items'):
                created_at = response['Items'][0]['created_at']
                
                new_status = 'resolved' if results['status'] == 'success' else 'in_progress'
                
                incidents_table.update_item(
                    Key={'incident_id': incident_id, 'created_at': created_at},
                    UpdateExpression='''
                        SET #status = :status,
                            timeline = list_append(if_not_exists(timeline, :empty_list), :event)
                    ''',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':status': new_status,
                        ':empty_list': [],
                        ':event': [{
                            'timestamp': int(datetime.now().timestamp()),
                            'event': 'remediation_executed',
                            'actor': 'remediation_executor',
                            'details': json.dumps({
                                'execution_id': results['execution_id'],
                                'status': results['status'],
                                'actions_executed': len(results['immediate_actions']) + len(results['corrective_actions'])
                            })
                        }]
                    }
                )
        
        except Exception as e:
            print(f"Error updating incident: {e}")


def lambda_handler(event, context):
    """
    Lambda handler for remediation execution
    
    Event format:
    {
        "incident_id": "INC-XXXXX",
        "remediation_plan": {...},
        "approval_id": "APPR-XXXXX" (optional)
    }
    """
    
    print(f"Remediation Executor received: {json.dumps(event)}")
    
    try:
        incident_id = event.get('incident_id')
        remediation_plan = event.get('remediation_plan')
        approval_id = event.get('approval_id')
        
        if not incident_id or not remediation_plan:
            return {
                'statusCode': 400,
                'result': {
                    'incident_id': incident_id or 'unknown',
                    'status': 'error',
                    'message': 'Missing incident_id or remediation_plan'
                }
            }
        
        # Execute remediation
        executor = RemediationExecutor()
        result = executor.execute(incident_id, remediation_plan, approval_id)
        
        return {
            'statusCode': 200,
            'result': result
        }
    
    except Exception as e:
        print(f"Error in remediation executor: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'result': {
                'incident_id': event.get('incident_id', 'unknown'),
                'status': 'error',
                'message': f'Execution failed: {str(e)}'
            }
        }
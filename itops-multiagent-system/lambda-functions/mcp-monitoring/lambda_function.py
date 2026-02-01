"""
MCP Server for Monitoring Tools (Lambda Implementation)
Provides CloudWatch metrics and logs access to AI agents
"""

import json
import boto3
from datetime import datetime, timedelta
from typing import Dict, Any

# Initialize AWS clients
cloudwatch = boto3.client('cloudwatch')
logs = boto3.client('logs')
dynamodb = boto3.resource('dynamodb')

# Circuit Breaker Table for fault tolerance
circuit_breaker_table = dynamodb.Table('ITOps-CircuitBreaker')

class CircuitBreaker:
    """
    Circuit breaker pattern implementation
    Prevents cascading failures by temporarily blocking calls to failing services
    """
    
    def __init__(self, service_name: str, failure_threshold: int = 5, timeout: int = 60):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
    
    def get_state(self) -> Dict:
        """Get current circuit breaker state from DynamoDB"""
        try:
            response = circuit_breaker_table.get_item(Key={'service_name': self.service_name})
            return response.get('Item', {
                'service_name': self.service_name,
                'state': 'CLOSED',
                'failure_count': 0,
                'last_failure_time': 0
            })
        except Exception as e:
            print(f"Error getting circuit breaker state: {e}")
            return {'service_name': self.service_name, 'state': 'CLOSED', 'failure_count': 0}
    
    def record_success(self):
        """Record successful call - resets circuit breaker"""
        try:
            circuit_breaker_table.put_item(
                Item={
                    'service_name': self.service_name,
                    'state': 'CLOSED',
                    'failure_count': 0,
                    'last_success_time': int(datetime.now().timestamp()),
                    'ttl': int(datetime.now().timestamp()) + 300
                }
            )
        except Exception as e:
            print(f"Error recording success: {e}")
    
    def record_failure(self):
        """Record failed call - may open circuit"""
        state = self.get_state()
        failure_count = state.get('failure_count', 0) + 1
        new_state = 'OPEN' if failure_count >= self.failure_threshold else 'CLOSED'
        
        try:
            circuit_breaker_table.put_item(
                Item={
                    'service_name': self.service_name,
                    'state': new_state,
                    'failure_count': failure_count,
                    'last_failure_time': int(datetime.now().timestamp()),
                    'ttl': int(datetime.now().timestamp()) + self.timeout
                }
            )
        except Exception as e:
            print(f"Error recording failure: {e}")
    
    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)"""
        state = self.get_state()
        
        if state.get('state') == 'OPEN':
            last_failure = state.get('last_failure_time', 0)
            # Half-open after timeout
            if datetime.now().timestamp() - last_failure > self.timeout:
                return False
            return True
        
        return False

class MCPTools:
    """MCP Tool implementations for monitoring"""
    
    def __init__(self):
        self.cloudwatch_breaker = CircuitBreaker('cloudwatch')
        self.logs_breaker = CircuitBreaker('cloudwatch_logs')
    
    def get_cpu_metrics(self, params: Dict) -> Dict:
        """
        Get CPU/Duration metrics for Lambda functions or EC2 instances
        
        Args:
            params: {
                'resource_id': str,
                'resource_type': 'Lambda' or 'EC2',
                'hours': int
            }
        
        Returns:
            Dict with metrics data or error
        """
        
        # Check circuit breaker
        if self.cloudwatch_breaker.is_open():
            return {'error': 'Circuit breaker OPEN for CloudWatch', 'retry_after': 60}
        
        try:
            resource_id = params.get('resource_id', '')
            resource_type = params.get('resource_type', 'Lambda')
            hours = params.get('hours', 1)
            
            # Set namespace and metric based on resource type
            namespace = 'AWS/Lambda' if resource_type == 'Lambda' else 'AWS/EC2'
            metric_name = 'Duration' if resource_type == 'Lambda' else 'CPUUtilization'
            
            # Set dimensions
            dimensions = []
            if resource_type == 'Lambda':
                dimensions = [{'Name': 'FunctionName', 'Value': resource_id}]
            else:
                dimensions = [{'Name': 'InstanceId', 'Value': resource_id}]
            
            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours)
            
            # Get metrics from CloudWatch
            response = cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=300,  # 5 minute intervals
                Statistics=['Average', 'Maximum']
            )
            
            # Record success
            self.cloudwatch_breaker.record_success()
            
            # Process and return results
            datapoints = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])
            
            return {
                'resource_id': resource_id,
                'resource_type': resource_type,
                'metric': metric_name,
                'datapoints': [
                    {
                        'timestamp': dp['Timestamp'].isoformat(),
                        'average': dp['Average'],
                        'maximum': dp['Maximum']
                    } for dp in datapoints
                ],
                'summary': {
                    'avg': sum(d['Average'] for d in datapoints) / len(datapoints) if datapoints else 0,
                    'max': max((d['Maximum'] for d in datapoints), default=0),
                    'count': len(datapoints)
                }
            }
            
        except Exception as e:
            self.cloudwatch_breaker.record_failure()
            return {'error': str(e)}
    
    def get_error_logs(self, params: Dict) -> Dict:
        """
        Get error logs from CloudWatch Logs
        
        Args:
            params: {
                'log_group': str,
                'hours': int,
                'pattern': str (default: 'ERROR')
            }
        
        Returns:
            Dict with log events or error
        """
        
        # Check circuit breaker
        if self.logs_breaker.is_open():
            return {'error': 'Circuit breaker OPEN for CloudWatch Logs', 'retry_after': 60}
        
        try:
            log_group = params.get('log_group', '/aws/lambda/*')
            hours = params.get('hours', 1)
            error_pattern = params.get('pattern', 'ERROR')
            
            # Calculate time range (CloudWatch Logs uses milliseconds)
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
            
            # Query logs
            response = logs.filter_log_events(
                logGroupName=log_group,
                startTime=start_time,
                endTime=end_time,
                filterPattern=error_pattern,
                limit=100
            )
            
            # Record success
            self.logs_breaker.record_success()
            
            events = response.get('events', [])
            
            return {
                'log_group': log_group,
                'pattern': error_pattern,
                'event_count': len(events),
                'events': [
                    {
                        'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                        'message': event['message'][:500]  # Truncate long messages
                    }
                    for event in events[:20]  # Limit to 20 events
                ],
                'time_range': {
                    'start': datetime.fromtimestamp(start_time / 1000).isoformat(),
                    'end': datetime.fromtimestamp(end_time / 1000).isoformat()
                }
            }
            
        except Exception as e:
            self.logs_breaker.record_failure()
            return {'error': str(e)}
    
    def check_service_health(self, params: Dict) -> Dict:
        """
        Check overall health of a service
        Combines metrics and logs for comprehensive health assessment
        
        Args:
            params: {
                'service_name': str
            }
        
        Returns:
            Dict with health status and recommendations
        """
        
        try:
            service_name = params.get('service_name', '')
            
            # Get error rate from logs
            error_logs = self.get_error_logs({
                'log_group': f'/aws/lambda/{service_name}',
                'hours': 1,
                'pattern': 'ERROR'
            })
            
            # Get performance metrics
            cpu_metrics = self.get_cpu_metrics({
                'resource_id': service_name,
                'resource_type': 'Lambda',
                'hours': 1
            })
            
            # Determine health status
            error_count = error_logs.get('event_count', 0)
            avg_duration = cpu_metrics.get('summary', {}).get('avg', 0)
            max_duration = cpu_metrics.get('summary', {}).get('max', 0)
            
            # Health logic
            health_status = 'healthy'
            issues = []
            
            if error_count > 10:
                health_status = 'unhealthy'
                issues.append(f'High error rate: {error_count} errors in past hour')
            elif error_count > 5:
                health_status = 'degraded'
                issues.append(f'Elevated error rate: {error_count} errors')
            
            if avg_duration > 5000:
                health_status = 'degraded' if health_status == 'healthy' else health_status
                issues.append(f'High average latency: {avg_duration}ms')
            
            if max_duration > 10000:
                health_status = 'degraded' if health_status == 'healthy' else health_status
                issues.append(f'Peak latency spike: {max_duration}ms')
            
            return {
                'service_name': service_name,
                'health_status': health_status,
                'metrics': {
                    'error_count': error_count,
                    'avg_duration_ms': avg_duration,
                    'max_duration_ms': max_duration
                },
                'issues': issues,
                'recommendation': self._get_health_recommendation(health_status, error_count, avg_duration),
                'checked_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def _get_health_recommendation(self, status, errors, duration):
        """Generate health recommendations based on status"""
        if status == 'unhealthy':
            return f"Service is unhealthy with {errors} errors. Immediate investigation required. Check logs and consider rolling back recent changes."
        elif status == 'degraded':
            return f"Service performance degraded. Review recent deployments, check resource utilization, and consider scaling."
        else:
            return "Service is operating normally. Continue monitoring."

def lambda_handler(event, context):
    """
    MCP Lambda Handler
    Supports MCP protocol for tool discovery and execution
    
    Event structure:
    {
        "action": "list_tools" | "execute",
        "tool_name": "get_cpu_metrics" | "get_error_logs" | "check_service_health",
        "parameters": {...}
    }
    """
    
    print(f"Received event: {json.dumps(event)}")
    
    try:
        tools = MCPTools()
        action = event.get('action', 'execute')
        
        # Handle tool discovery
        if action == 'list_tools':
            return {
                'statusCode': 200,
                'tools': [
                    {
                        'name': 'get_cpu_metrics',
                        'description': 'Get CPU/Duration metrics for Lambda functions or EC2 instances over a specified time period',
                        'parameters': {
                            'resource_id': 'Resource identifier (function name or instance ID)',
                            'resource_type': 'Lambda or EC2',
                            'hours': 'Number of hours to look back (default: 1)'
                        },
                        'returns': 'Metrics data with average and maximum values'
                    },
                    {
                        'name': 'get_error_logs',
                        'description': 'Get error logs from CloudWatch Logs for debugging and troubleshooting',
                        'parameters': {
                            'log_group': 'Log group name (e.g., /aws/lambda/FunctionName)',
                            'hours': 'Number of hours to look back (default: 1)',
                            'pattern': 'Search pattern (default: ERROR)'
                        },
                        'returns': 'List of log events matching the pattern'
                    },
                    {
                        'name': 'check_service_health',
                        'description': 'Check overall health status of a service by analyzing errors and performance metrics',
                        'parameters': {
                            'service_name': 'Name of the service to check'
                        },
                        'returns': 'Health status (healthy/degraded/unhealthy) with recommendations'
                    }
                ]
            }
        
        # Handle tool execution
        elif action == 'execute':
            tool_name = event.get('tool_name')
            parameters = event.get('parameters', {})
            
            if tool_name == 'get_cpu_metrics':
                result = tools.get_cpu_metrics(parameters)
            elif tool_name == 'get_error_logs':
                result = tools.get_error_logs(parameters)
            elif tool_name == 'check_service_health':
                result = tools.check_service_health(parameters)
            else:
                return {
                    'statusCode': 400,
                    'error': f'Unknown tool: {tool_name}'
                }
            
            return {
                'statusCode': 200,
                'result': result
            }
        
        else:
            return {
                'statusCode': 400,
                'error': f'Unknown action: {action}'
            }
    
    except Exception as e:
        print(f"Error in MCP handler: {e}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'error': str(e)
        }
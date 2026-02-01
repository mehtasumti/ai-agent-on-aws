"""
MCP Server for Incident Management
Handles incident CRUD operations and AI analysis
"""

import json
import boto3
from datetime import datetime
import uuid
from typing import Dict

dynamodb = boto3.resource('dynamodb')
bedrock_runtime = boto3.client('bedrock-runtime')

incidents_table = dynamodb.Table('ITOps-Incidents')
kb_table = dynamodb.Table('ITOps-KnowledgeBase')

class IncidentTools:
    """Incident management tools"""
    
    def create_incident(self, params: Dict) -> Dict:
        """Create a new incident"""
        try:
            incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
            timestamp = int(datetime.now().timestamp())
            
            incident = {
                'incident_id': incident_id,
                'created_at': timestamp,
                'title': params['title'],
                'description': params['description'],
                'severity': params.get('severity', 'medium'),
                'status': 'open',
                'affected_services': params.get('affected_services', []),
                'detected_by': params.get('detected_by', 'system'),
                'assigned_to': params.get('assigned_to', 'unassigned'),
                'timeline': [
                    {
                        'timestamp': timestamp,
                        'event': 'incident_created',
                        'actor': params.get('detected_by', 'system'),
                        'details': 'Incident created in system'
                    }
                ],
                'metadata': params.get('metadata', {})
            }
            
            incidents_table.put_item(Item=incident)
            
            return {
                'success': True,
                'incident_id': incident_id,
                'incident': incident
            }
        
        except Exception as e:
            return {'error': str(e)}
    
    def get_incident(self, params: Dict) -> Dict:
        """Get incident details"""
        try:
            incident_id = params['incident_id']
            
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            items = response.get('Items', [])
            
            if not items:
                return {'error': 'Incident not found'}
            
            return {
                'success': True,
                'incident': items[0]
            }
        
        except Exception as e:
            return {'error': str(e)}
    
    def update_incident(self, params: Dict) -> Dict:
        """Update incident status"""
        try:
            incident_id = params['incident_id']
            updates = params.get('updates', {})
            updated_by = params.get('updated_by', 'system')
            
            # Get current incident
            incident_response = self.get_incident({'incident_id': incident_id})
            if 'error' in incident_response:
                return incident_response
            
            incident = incident_response['incident']
            created_at = incident['created_at']
            
            # Prepare update expression
            update_expression_parts = []
            expression_values = {}
            expression_names = {}
            
            for key, value in updates.items():
                if key not in ['incident_id', 'created_at', 'timeline']:
                    update_expression_parts.append(f"#{key} = :{key}")
                    expression_values[f":{key}"] = value
                    expression_names[f"#{key}"] = key
            
            # Add timeline entry
            timeline_entry = {
                'timestamp': int(datetime.now().timestamp()),
                'event': 'incident_updated',
                'actor': updated_by,
                'details': f"Updated: {', '.join(updates.keys())}"
            }
            
            update_expression_parts.append("timeline = list_append(timeline, :new_event)")
            expression_values[':new_event'] = [timeline_entry]
            
            update_expression = "SET " + ", ".join(update_expression_parts)
            
            incidents_table.update_item(
                Key={
                    'incident_id': incident_id,
                    'created_at': created_at
                },
                UpdateExpression=update_expression,
                ExpressionAttributeNames=expression_names if expression_names else None,
                ExpressionAttributeValues=expression_values
            )
            
            return {
                'success': True,
                'incident_id': incident_id,
                'updated_fields': list(updates.keys())
            }
        
        except Exception as e:
            return {'error': str(e)}
    
    def analyze_incident(self, params: Dict) -> Dict:
        """AI-powered incident analysis"""
        try:
            incident_id = params['incident_id']
            analysis_type = params.get('analysis_type', 'root_cause')
            
            # Get incident
            incident_response = self.get_incident({'incident_id': incident_id})
            if 'error' in incident_response:
                return incident_response
            
            incident = incident_response['incident']
            
            # Build analysis prompt
            if analysis_type == 'root_cause':
                prompt = f"""Analyze this IT incident and identify the most likely root cause:

**Incident Details:**
- ID: {incident['incident_id']}
- Title: {incident['title']}
- Description: {incident['description']}
- Severity: {incident['severity']}
- Affected Services: {', '.join(incident.get('affected_services', ['Unknown']))}
- Current Status: {incident['status']}

**Timeline:**
{self._format_timeline(incident.get('timeline', []))}

Provide:
1. Top 3 most likely root causes (ranked by probability)
2. Supporting evidence for each
3. Next steps for verification
4. Recommended remediation approach

Be specific and actionable."""

            elif analysis_type == 'impact':
                prompt = f"""Assess the impact of this IT incident:

**Incident Details:**
- Title: {incident['title']}
- Description: {incident['description']}
- Affected Services: {', '.join(incident.get('affected_services', ['Unknown']))}

Provide:
1. Immediate user/system impact
2. Potential cascading effects
3. Business impact assessment
4. Affected stakeholders
5. Recommended communication plan"""

            elif analysis_type == 'similar_incidents':
                prompt = f"""Find similar historical incidents:

**Current Incident:**
- Title: {incident['title']}
- Description: {incident['description']}
- Services: {', '.join(incident.get('affected_services', []))}

Analyze patterns and provide:
1. Similar incident patterns
2. Common root causes
3. Successful resolution strategies
4. Prevention recommendations"""
            
            else:
                return {'error': f'Unknown analysis type: {analysis_type}'}
            
            # Call Bedrock
            response = bedrock_runtime.invoke_model(
                modelId='anthropic.claude-3-5-sonnet-20241022-v2:0',
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "temperature": 0.7,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                })
            )
            
            response_body = json.loads(response['body'].read())
            analysis = response_body['content'][0]['text']
            
            # Update incident with analysis
            created_at = incident['created_at']
            incidents_table.update_item(
                Key={
                    'incident_id': incident_id,
                    'created_at': created_at
                },
                UpdateExpression='SET timeline = list_append(timeline, :new_event)',
                ExpressionAttributeValues={
                    ':new_event': [{
                        'timestamp': int(datetime.now().timestamp()),
                        'event': f'ai_analysis_{analysis_type}',
                        'actor': 'ai_agent',
                        'details': analysis
                    }]
                }
            )
            
            return {
                'success': True,
                'analysis_type': analysis_type,
                'analysis': analysis,
                'incident_id': incident_id
            }
        
        except Exception as e:
            return {'error': str(e)}
    
    def list_incidents(self, params: Dict) -> Dict:
        """List incidents with filters"""
        try:
            status = params.get('status')
            severity = params.get('severity')
            limit = params.get('limit', 20)
            
            if status:
                response = incidents_table.query(
                    IndexName='status-index',
                    KeyConditionExpression='#status = :status',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={':status': status},
                    Limit=limit,
                    ScanIndexForward=False
                )
            else:
                response = incidents_table.scan(Limit=limit)
            
            incidents = response.get('Items', [])
            
            # Filter by severity if specified
            if severity:
                incidents = [i for i in incidents if i.get('severity') == severity]
            
            return {
                'success': True,
                'incidents': incidents,
                'count': len(incidents)
            }
        
        except Exception as e:
            return {'error': str(e)}
    
    def _format_timeline(self, timeline):
        """Format timeline for display"""
        formatted = []
        for event in timeline[-5:]:  # Last 5 events
            ts = datetime.fromtimestamp(event['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            formatted.append(f"- {ts}: {event['event']} - {event.get('details', '')}")
        return '\n'.join(formatted)

def lambda_handler(event, context):
    """MCP Incident Management Handler"""
    
    print(f"Received event: {json.dumps(event)}")
    
    try:
        tools = IncidentTools()
        action = event.get('action', 'execute')
        
        if action == 'list_tools':
            return {
                'statusCode': 200,
                'tools': [
                    {
                        'name': 'create_incident',
                        'description': 'Create a new incident',
                        'parameters': {
                            'title': 'Incident title',
                            'description': 'Detailed description',
                            'severity': 'critical, high, medium, or low',
                            'affected_services': 'List of affected services',
                            'detected_by': 'Who detected the incident'
                        }
                    },
                    {
                        'name': 'get_incident',
                        'description': 'Get incident details',
                        'parameters': {
                            'incident_id': 'Incident ID'
                        }
                    },
                    {
                        'name': 'update_incident',
                        'description': 'Update incident status or details',
                        'parameters': {
                            'incident_id': 'Incident ID',
                            'updates': 'Dictionary of fields to update',
                            'updated_by': 'Who is updating'
                        }
                    },
                    {
                        'name': 'analyze_incident',
                        'description': 'AI-powered incident analysis',
                        'parameters': {
                            'incident_id': 'Incident ID',
                            'analysis_type': 'root_cause, impact, or similar_incidents'
                        }
                    },
                    {
                        'name': 'list_incidents',
                        'description': 'List incidents with optional filters',
                        'parameters': {
                            'status': 'Filter by status',
                            'severity': 'Filter by severity',
                            'limit': 'Maximum number of results'
                        }
                    }
                ]
            }
        
        elif action == 'execute':
            tool_name = event.get('tool_name')
            parameters = event.get('parameters', {})
            
            if tool_name == 'create_incident':
                result = tools.create_incident(parameters)
            elif tool_name == 'get_incident':
                result = tools.get_incident(parameters)
            elif tool_name == 'update_incident':
                result = tools.update_incident(parameters)
            elif tool_name == 'analyze_incident':
                result = tools.analyze_incident(parameters)
            elif tool_name == 'list_incidents':
                result = tools.list_incidents(parameters)
            else:
                return {'statusCode': 400, 'error': f'Unknown tool: {tool_name}'}
            
            return {'statusCode': 200, 'result': result}
        
        else:
            return {'statusCode': 400, 'error': f'Unknown action: {action}'}
    
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 500, 'error': str(e)}
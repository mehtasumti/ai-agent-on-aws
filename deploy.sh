#!/bin/bash

################################################################################
# Multi-Agent IT Operations System - Complete Deployment Script
# 
# This script deploys the entire production-ready multi-agent system including:
# - DynamoDB tables for state management
# - IAM roles with least privilege
# - Lambda functions for agents and MCP servers
# - Step Functions for orchestration
# - API Gateway for REST API
# - S3-hosted Web UI
# - CloudWatch dashboards and alarms
################################################################################

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
AWS_REGION=${AWS_REGION:-us-east-1}
ENVIRONMENT=${ENVIRONMENT:-production}
PROJECT_NAME="itops-multiagent"
TIMESTAMP=$(date +%s)
S3_BUCKET_NAME="${PROJECT_NAME}-ui-${TIMESTAMP}"

# Header
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║   Multi-Agent IT Operations System                        ║
║   Automated Deployment                                    ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

echo -e "${YELLOW}Configuration:${NC}"
echo -e "  Region:      ${GREEN}$AWS_REGION${NC}"
echo -e "  Environment: ${GREEN}$ENVIRONMENT${NC}"
echo -e "  Timestamp:   ${GREEN}$TIMESTAMP${NC}\n"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found. Please install it first."
        exit 1
    fi
    log_success "AWS CLI found"
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured properly"
        exit 1
    fi
    log_success "AWS credentials configured"
    
    # Check required files exist
    required_files=(
        "infrastructure/dynamodb-tables.yaml"
        "infrastructure/iam-roles.yaml"
        "infrastructure/cloudwatch-dashboard.yaml"
        "step-functions/multi-agent-orchestrator.json"
        "web-ui/index.html"
    )
    
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            log_error "Required file not found: $file"
            exit 1
        fi
    done
    log_success "All required files present"
}

# Get AWS Account ID
get_account_info() {
    log_info "Retrieving AWS account information..."
    
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    AWS_USER=$(aws sts get-caller-identity --query Arn --output text)
    
    log_success "Account ID: $AWS_ACCOUNT_ID"
    log_success "User: $AWS_USER"
}

# Deploy CloudFormation stack
deploy_stack() {
    local stack_name=$1
    local template_file=$2
    local capabilities=$3
    
    log_info "Deploying stack: $stack_name..."
    
    if aws cloudformation describe-stacks --stack-name "$stack_name" --region "$AWS_REGION" &> /dev/null; then
        log_warning "Stack $stack_name already exists, updating..."
        
        aws cloudformation update-stack \
            --stack-name "$stack_name" \
            --template-body "file://$template_file" \
            ${capabilities:+--capabilities $capabilities} \
            --region "$AWS_REGION" 2>&1 | grep -v "No updates are to be performed" || true
        
        aws cloudformation wait stack-update-complete \
            --stack-name "$stack_name" \
            --region "$AWS_REGION" 2>/dev/null || true
    else
        aws cloudformation create-stack \
            --stack-name "$stack_name" \
            --template-body "file://$template_file" \
            ${capabilities:+--capabilities $capabilities} \
            --region "$AWS_REGION"
        
        aws cloudformation wait stack-create-complete \
            --stack-name "$stack_name" \
            --region "$AWS_REGION"
    fi
    
    log_success "Stack $stack_name deployed"
}

# Deploy DynamoDB tables
deploy_dynamodb() {
    log_info "Step 1/9: Deploying DynamoDB tables..."
    deploy_stack "ITOps-DynamoDB" "infrastructure/dynamodb-tables.yaml"
}

# Deploy IAM roles
deploy_iam() {
    log_info "Step 2/9: Deploying IAM roles..."
    deploy_stack "ITOps-IAM" "infrastructure/iam-roles.yaml" "CAPABILITY_NAMED_IAM"
    
    # Retrieve role ARNs
    LAMBDA_ROLE_ARN=$(aws cloudformation describe-stacks \
        --stack-name ITOps-IAM \
        --query 'Stacks[0].Outputs[?OutputKey==`LambdaExecutionRoleArn`].OutputValue' \
        --output text \
        --region "$AWS_REGION")
    
    STEPFUNCTIONS_ROLE_ARN=$(aws cloudformation describe-stacks \
        --stack-name ITOps-IAM \
        --query 'Stacks[0].Outputs[?OutputKey==`StepFunctionsExecutionRoleArn`].OutputValue' \
        --output text \
        --region "$AWS_REGION")
    
    log_success "Lambda Role ARN: $LAMBDA_ROLE_ARN"
    log_success "Step Functions Role ARN: $STEPFUNCTIONS_ROLE_ARN"
}

# Deploy Lambda function
deploy_lambda_function() {
    local function_name=$1
    local source_dir=$2
    local handler=${3:-lambda_function.lambda_handler}
    local timeout=${4:-60}
    local memory=${5:-512}
    
    log_info "  Deploying Lambda: $function_name..."
    
    # Create temporary build directory
    BUILD_DIR=$(mktemp -d)
    
    # Copy source files
    cp -r "$source_dir"/* "$BUILD_DIR/"
    
    # Install dependencies if requirements.txt exists
    if [ -f "$BUILD_DIR/requirements.txt" ]; then
        pip install -r "$BUILD_DIR/requirements.txt" -t "$BUILD_DIR" --quiet --disable-pip-version-check 2>/dev/null || true
    fi
    
    # Create deployment package
    cd "$BUILD_DIR"
    zip -qr function.zip . -x "*.pyc" -x "__pycache__/*" -x "*.dist-info/*"
    
    # Create or update function
    if aws lambda get-function --function-name "$function_name" --region "$AWS_REGION" &> /dev/null; then
        aws lambda update-function-code \
            --function-name "$function_name" \
            --zip-file fileb://function.zip \
            --region "$AWS_REGION" > /dev/null
        
        aws lambda update-function-configuration \
            --function-name "$function_name" \
            --timeout "$timeout" \
            --memory-size "$memory" \
            --region "$AWS_REGION" > /dev/null
    else
        aws lambda create-function \
            --function-name "$function_name" \
            --runtime python3.12 \
            --role "$LAMBDA_ROLE_ARN" \
            --handler "$handler" \
            --zip-file fileb://function.zip \
            --timeout "$timeout" \
            --memory-size "$memory" \
            --region "$AWS_REGION" > /dev/null
    fi
    
    # Cleanup
    cd - > /dev/null
    rm -rf "$BUILD_DIR"
    
    log_success "  $function_name deployed"
}

# Deploy all Lambda functions
deploy_lambda_functions() {
    log_info "Step 3/9: Deploying Lambda functions..."
    
    # Wait for IAM role to propagate
    sleep 10
    
    # MCP Servers
    deploy_lambda_function "ITOps-MCP-Monitoring" "lambda-functions/mcp-monitoring" "lambda_function.lambda_handler" 60 512
    deploy_lambda_function "ITOps-MCP-Incident" "lambda-functions/mcp-incident" "lambda_function.lambda_handler" 120 1024
    
    # AI Agents
    deploy_lambda_function "ITOps-Agent-Triage" "lambda-functions/agent-triage" "lambda_function.lambda_handler" 120 1024
    deploy_lambda_function "ITOps-Agent-RootCause" "lambda-functions/agent-rootcause" "lambda_function.lambda_handler" 120 1024
    deploy_lambda_function "ITOps-Agent-Remediation" "lambda-functions/agent-remediation" "lambda_function.lambda_handler" 120 1024
    
    # Support Functions
    deploy_lambda_function "ITOps-RequestApproval" "lambda-functions/approval-handler" "lambda_function.lambda_handler" 30 512
    deploy_lambda_function "ITOps-ProcessApproval" "lambda-functions/process-approval" "lambda_function.lambda_handler" 30 512
    deploy_lambda_function "ITOps-ExecuteRemediation" "lambda-functions/execute-remediation" "lambda_function.lambda_handler" 600 512
    deploy_lambda_function "ITOps-VerifyResolution" "lambda-functions/verify-resolution" "lambda_function.lambda_handler" 60 512
    deploy_lambda_function "ITOps-EscalateIncident" "lambda-functions/escalate-incident" "lambda_function.lambda_handler" 30 512
    deploy_lambda_function "ITOps-TestDataGenerator" "lambda-functions/test-data-generator" "lambda_function.lambda_handler" 60 512
    deploy_lambda_function "ITOps-TriggerWorkflow" "lambda-functions/trigger-workflow" "lambda_function.lambda_handler" 30 512
    
    log_success "All Lambda functions deployed"
}

# Deploy Step Functions
deploy_step_functions() {
    log_info "Step 4/9: Deploying Step Functions state machine..."
    
    # Replace placeholders in state machine definition
    STATE_MACHINE_DEF=$(cat step-functions/multi-agent-orchestrator.json | \
        sed "s/ACCOUNT_ID/$AWS_ACCOUNT_ID/g" | \
        sed "s/REGION/$AWS_REGION/g")
    
    STATE_MACHINE_ARN="arn:aws:states:$AWS_REGION:$AWS_ACCOUNT_ID:stateMachine:ITOps-MultiAgentOrchestrator"
    
    # Create or update state machine
    if aws stepfunctions describe-state-machine --state-machine-arn "$STATE_MACHINE_ARN" --region "$AWS_REGION" &> /dev/null; then
        aws stepfunctions update-state-machine \
            --state-machine-arn "$STATE_MACHINE_ARN" \
            --definition "$STATE_MACHINE_DEF" \
            --region "$AWS_REGION" > /dev/null
    else
        aws stepfunctions create-state-machine \
            --name ITOps-MultiAgentOrchestrator \
            --definition "$STATE_MACHINE_DEF" \
            --role-arn "$STEPFUNCTIONS_ROLE_ARN" \
            --region "$AWS_REGION" > /dev/null
    fi
    
    log_success "Step Functions deployed"
}

# Deploy API Gateway
deploy_api_gateway() {
    log_info "Step 5/9: Deploying API Gateway..."
    
    # Check if API exists
    API_ID=$(aws apigateway get-rest-apis \
        --query "items[?name=='ITOps-MultiAgent-API'].id" \
        --output text \
        --region "$AWS_REGION")
    
    # Create API if it doesn't exist
    if [ -z "$API_ID" ]; then
        API_ID=$(aws apigateway create-rest-api \
            --name ITOps-MultiAgent-API \
            --description "API for IT Operations Multi-Agent System" \
            --endpoint-configuration types=REGIONAL \
            --query 'id' \
            --output text \
            --region "$AWS_REGION")
    fi
    
    log_success "API Gateway ID: $API_ID"
    
    # Get root resource
    ROOT_ID=$(aws apigateway get-resources \
        --rest-api-id "$API_ID" \
        --query "items[?path=='/'].id" \
        --output text \
        --region "$AWS_REGION")
    
    # Create /incidents resource if it doesn't exist
    INCIDENTS_ID=$(aws apigateway get-resources \
        --rest-api-id "$API_ID" \
        --query "items[?pathPart=='incidents'].id" \
        --output text \
        --region "$AWS_REGION")
    
    if [ -z "$INCIDENTS_ID" ]; then
        INCIDENTS_ID=$(aws apigateway create-resource \
            --rest-api-id "$API_ID" \
            --parent-id "$ROOT_ID" \
            --path-part incidents \
            --query 'id' \
            --output text \
            --region "$AWS_REGION")
    fi
    
    # Configure POST /incidents
    aws apigateway put-method \
        --rest-api-id "$API_ID" \
        --resource-id "$INCIDENTS_ID" \
        --http-method POST \
        --authorization-type NONE \
        --region "$AWS_REGION" 2>/dev/null || true
    
    aws apigateway put-integration \
        --rest-api-id "$API_ID" \
        --resource-id "$INCIDENTS_ID" \
        --http-method POST \
        --type AWS_PROXY \
        --integration-http-method POST \
        --uri "arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:ITOps-MCP-Incident/invocations" \
        --region "$AWS_REGION" 2>/dev/null || true
    
    # Configure GET /incidents
    aws apigateway put-method \
        --rest-api-id "$API_ID" \
        --resource-id "$INCIDENTS_ID" \
        --http-method GET \
        --authorization-type NONE \
        --region "$AWS_REGION" 2>/dev/null || true
    
    aws apigateway put-integration \
        --rest-api-id "$API_ID" \
        --resource-id "$INCIDENTS_ID" \
        --http-method GET \
        --type AWS_PROXY \
        --integration-http-method POST \
        --uri "arn:aws:apigateway:$AWS_REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:ITOps-MCP-Incident/invocations" \
        --region "$AWS_REGION" 2>/dev/null || true
    
    # Add Lambda permissions
    aws lambda add-permission \
        --function-name ITOps-MCP-Incident \
        --statement-id apigateway-invoke-post \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:$AWS_REGION:$AWS_ACCOUNT_ID:$API_ID/*/POST/incidents" \
        --region "$AWS_REGION" 2>/dev/null || true
    
    aws lambda add-permission \
        --function-name ITOps-MCP-Incident \
        --statement-id apigateway-invoke-get \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:$AWS_REGION:$AWS_ACCOUNT_ID:$API_ID/*/GET/incidents" \
        --region "$AWS_REGION" 2>/dev/null || true
    
    # Deploy API
    aws apigateway create-deployment \
        --rest-api-id "$API_ID" \
        --stage-name prod \
        --region "$AWS_REGION" > /dev/null
    
    API_ENDPOINT="https://$API_ID.execute-api.$AWS_REGION.amazonaws.com/prod"
    log_success "API Gateway deployed: $API_ENDPOINT"
}

# Create S3 bucket for web UI
create_s3_bucket() {
    log_info "Step 6/9: Creating S3 bucket for web UI..."
    
    # Create bucket
    if [ "$AWS_REGION" == "us-east-1" ]; then
        aws s3 mb "s3://$S3_BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null || true
    else
        aws s3 mb "s3://$S3_BUCKET_NAME" --region "$AWS_REGION" --create-bucket-configuration LocationConstraint="$AWS_REGION" 2>/dev/null || true
    fi
    
    # Disable block public access
    aws s3api put-public-access-block \
        --bucket "$S3_BUCKET_NAME" \
        --public-access-block-configuration "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false" \
        --region "$AWS_REGION"
    
    # Enable static website hosting
    aws s3 website "s3://$S3_BUCKET_NAME" \
        --index-document index.html \
        --region "$AWS_REGION"
    
    # Set bucket policy
    BUCKET_POLICY=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::$S3_BUCKET_NAME/*"
        }
    ]
}
EOF
)
    
    echo "$BUCKET_POLICY" | aws s3api put-bucket-policy \
        --bucket "$S3_BUCKET_NAME" \
        --policy file:///dev/stdin \
        --region "$AWS_REGION"
    
    log_success "S3 bucket created: $S3_BUCKET_NAME"
}

# Deploy web UI
deploy_web_ui() {
    log_info "Step 7/9: Deploying web UI..."
    
    # Update API endpoint in index.html
    sed "s|https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/prod|$API_ENDPOINT|g" \
        web-ui/index.html > /tmp/index.html
    
    # Upload to S3
    aws s3 cp /tmp/index.html "s3://$S3_BUCKET_NAME/index.html" \
        --content-type "text/html" \
        --region "$AWS_REGION"
    
    rm /tmp/index.html
    
    WEB_URL="http://$S3_BUCKET_NAME.s3-website-$AWS_REGION.amazonaws.com"
    log_success "Web UI deployed: $WEB_URL"
}

# Deploy CloudWatch dashboard
deploy_cloudwatch() {
    log_info "Step 8/9: Deploying CloudWatch dashboard and alarms..."
    deploy_stack "ITOps-Monitoring" "infrastructure/cloudwatch-dashboard.yaml"
    
    DASHBOARD_URL=$(aws cloudformation describe-stacks \
        --stack-name ITOps-Monitoring \
        --query 'Stacks[0].Outputs[?OutputKey==`DashboardURL`].OutputValue' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null || echo "N/A")
    
    log_success "CloudWatch monitoring deployed"
}

# Initialize system data
initialize_system() {
    log_info "Step 9/9: Initializing system data..."
    
    # Populate knowledge base
    log_info "  Populating knowledge base..."
    aws lambda invoke \
        --function-name ITOps-TestDataGenerator \
        --payload '{"action": "populate_kb"}' \
        --region "$AWS_REGION" \
        /tmp/kb-result.json > /dev/null
    
    # Generate test incidents
    log_info "  Generating test incidents..."
    aws lambda invoke \
        --function-name ITOps-TestDataGenerator \
        --payload '{"action": "generate_multiple", "count": 3}' \
        --region "$AWS_REGION" \
        /tmp/test-result.json > /dev/null
    
    log_success "System initialized with sample data"
}

# Save deployment information
save_deployment_info() {
    log_info "Saving deployment information..."
    
    cat > deployment-info.txt <<EOF
================================================================================
Multi-Agent IT Operations System - Deployment Information
================================================================================

Deployed: $(date)
Region: $AWS_REGION
Account ID: $AWS_ACCOUNT_ID
Environment: $ENVIRONMENT

================================================================================
ACCESS POINTS
================================================================================

Web UI:              $WEB_URL
API Endpoint:        $API_ENDPOINT
CloudWatch Dashboard: $DASHBOARD_URL

================================================================================
AWS RESOURCES
================================================================================

CloudFormation Stacks:
  - ITOps-DynamoDB
  - ITOps-IAM
  - ITOps-Monitoring

S3 Bucket:
  - $S3_BUCKET_NAME

API Gateway:
  - API ID: $API_ID

Step Functions:
  - ITOps-MultiAgentOrchestrator

DynamoDB Tables:
  - ITOps-Incidents
  - ITOps-AgentState
  - ITOps-KnowledgeBase
  - ITOps-ApprovalQueue
  - ITOps-CircuitBreaker
  - ITOps-Conversations

Lambda Functions:
  - ITOps-MCP-Monitoring
  - ITOps-MCP-Incident
  - ITOps-Agent-Triage
  - ITOps-Agent-RootCause
  - ITOps-Agent-Remediation
  - ITOps-RequestApproval
  - ITOps-ProcessApproval
  - ITOps-ExecuteRemediation
  - ITOps-VerifyResolution
  - ITOps-EscalateIncident
  - ITOps-TestDataGenerator
  - ITOps-TriggerWorkflow

================================================================================
NEXT STEPS
================================================================================

1. Open Web UI:
   $WEB_URL

2. View CloudWatch Dashboard:
   $DASHBOARD_URL

3. Run Integration Tests:
   python tests/integration_tests.py

4. Create an incident through Web UI and trigger AI resolution

5. Monitor execution in Step Functions console:
   https://console.aws.amazon.com/states/home?region=$AWS_REGION

================================================================================
CLEANUP
================================================================================

To remove all resources:
  ./cleanup.sh

================================================================================
EOF
    
    log_success "Deployment information saved to deployment-info.txt"
}

# Main deployment flow
main() {
    echo ""
    check_prerequisites
    echo ""
    get_account_info
    echo ""
    
    deploy_dynamodb
    deploy_iam
    deploy_lambda_functions
    deploy_step_functions
    deploy_api_gateway
    create_s3_bucket
    deploy_web_ui
    deploy_cloudwatch
    initialize_system
    
    echo ""
    save_deployment_info
    
    # Success summary
    echo ""
    echo -e "${GREEN}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                DEPLOYMENT COMPLETE! 🎉                    ║
╚═══════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    echo -e "${YELLOW}Quick Access:${NC}"
    echo -e "  Web UI:   ${GREEN}$WEB_URL${NC}"
    echo -e "  API:      ${GREEN}$API_ENDPOINT${NC}"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo -e "  1. Open the Web UI and create an incident"
    echo -e "  2. Trigger AI resolution to see agents in action"
    echo -e "  3. View CloudWatch dashboard for monitoring"
    echo -e "  4. Run: ${GREEN}python tests/integration_tests.py${NC}"
    echo ""
    echo -e "See ${GREEN}deployment-info.txt${NC} for complete details"
    echo ""
}

# Run main deployment
main

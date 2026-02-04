#!/bin/bash

################################################################################
# Multi-Agent IT Operations System - Cleanup Script
# 
# WARNING: This script will DELETE all resources created by the deployment
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

AWS_REGION=${AWS_REGION:-us-east-1}

# Header
echo -e "${RED}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║              WARNING: RESOURCE DELETION                   ║
║                                                           ║
║  This script will DELETE ALL resources including:         ║
║    - Lambda functions                                     ║
║    - DynamoDB tables (and all data)                       ║
║    - Step Functions                                       ║
║    - API Gateway                                          ║
║    - S3 buckets                                           ║
║    - CloudWatch dashboards and alarms                     ║
║    - IAM roles                                            ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}\n"

# Confirmation
echo -e "${YELLOW}Region: $AWS_REGION${NC}\n"
read -p "Type 'DELETE' to confirm deletion of all resources: " confirm

if [ "$confirm" != "DELETE" ]; then
    echo -e "\n${GREEN}Cleanup cancelled.${NC}"
    exit 0
fi

echo -e "\n${RED}Starting cleanup process...${NC}\n"

log_info() {
    echo -e "${YELLOW}[DELETING]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# Delete Lambda functions
delete_lambda_functions() {
    log_info "Deleting Lambda functions..."
    
    FUNCTIONS=(
        "ITOps-MCP-Monitoring"
        "ITOps-MCP-Incident"
        "ITOps-Agent-Triage"
        "ITOps-Agent-RootCause"
        "ITOps-Agent-Remediation"
        "ITOps-RequestApproval"
        "ITOps-ProcessApproval"
        "ITOps-ExecuteRemediation"
        "ITOps-VerifyResolution"
        "ITOps-EscalateIncident"
        "ITOps-TestDataGenerator"
        "ITOps-TriggerWorkflow"
    )
    
    for func in "${FUNCTIONS[@]}"; do
        aws lambda delete-function \
            --function-name "$func" \
            --region "$AWS_REGION" 2>/dev/null && \
            echo "  ✓ Deleted $func" || \
            echo "  ✗ $func not found or already deleted"
    done
    
    log_success "Lambda functions deleted"
}

# Delete Step Functions
delete_step_functions() {
    log_info "Deleting Step Functions..."
    
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    STATE_MACHINE_ARN="arn:aws:states:$AWS_REGION:$AWS_ACCOUNT_ID:stateMachine:ITOps-MultiAgentOrchestrator"
    
    # Stop all running executions
    RUNNING_EXECUTIONS=$(aws stepfunctions list-executions \
        --state-machine-arn "$STATE_MACHINE_ARN" \
        --status-filter RUNNING \
        --query 'executions[].executionArn' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null || echo "")
    
    if [ ! -z "$RUNNING_EXECUTIONS" ]; then
        for execution in $RUNNING_EXECUTIONS; do
            aws stepfunctions stop-execution \
                --execution-arn "$execution" \
                --region "$AWS_REGION" 2>/dev/null
        done
        echo "  ✓ Stopped running executions"
    fi
    
    # Delete state machine
    aws stepfunctions delete-state-machine \
        --state-machine-arn "$STATE_MACHINE_ARN" \
        --region "$AWS_REGION" 2>/dev/null && \
        echo "  ✓ Deleted state machine" || \
        echo "  ✗ State machine not found or already deleted"
    
    log_success "Step Functions deleted"
}

# Delete API Gateway
delete_api_gateway() {
    log_info "Deleting API Gateway..."
    
    API_ID=$(aws apigateway get-rest-apis \
        --query "items[?name=='ITOps-MultiAgent-API'].id" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)
    
    if [ ! -z "$API_ID" ]; then
        aws apigateway delete-rest-api \
            --rest-api-id "$API_ID" \
            --region "$AWS_REGION"
        echo "  ✓ Deleted API Gateway: $API_ID"
    else
        echo "  ✗ API Gateway not found"
    fi
    
    log_success "API Gateway deleted"
}

# Delete S3 buckets
delete_s3_buckets() {
    log_info "Deleting S3 buckets..."
    
    BUCKETS=$(aws s3api list-buckets \
        --query "Buckets[?starts_with(Name, 'itops-multiagent-ui')].Name" \
        --output text)
    
    if [ ! -z "$BUCKETS" ]; then
        for bucket in $BUCKETS; do
            # Empty bucket first
            aws s3 rm "s3://$bucket" --recursive --region "$AWS_REGION" 2>/dev/null
            # Delete bucket
            aws s3 rb "s3://$bucket" --force --region "$AWS_REGION" 2>/dev/null && \
                echo "  ✓ Deleted bucket: $bucket" || \
                echo "  ✗ Failed to delete bucket: $bucket"
        done
    else
        echo "  ✗ No buckets found"
    fi
    
    log_success "S3 buckets deleted"
}

# Delete CloudFormation stacks
delete_cloudformation_stacks() {
    log_info "Deleting CloudFormation stacks..."
    
    STACKS=("ITOps-Monitoring" "ITOps-IAM" "ITOps-DynamoDB")
    
    for stack in "${STACKS[@]}"; do
        if aws cloudformation describe-stacks --stack-name "$stack" --region "$AWS_REGION" &> /dev/null; then
            aws cloudformation delete-stack \
                --stack-name "$stack" \
                --region "$AWS_REGION"
            echo "  ✓ Initiated deletion of $stack"
        else
            echo "  ✗ Stack $stack not found"
        fi
    done
    
    # Wait for deletions
    log_info "Waiting for stack deletions to complete (this may take a few minutes)..."
    
    for stack in "${STACKS[@]}"; do
        if aws cloudformation describe-stacks --stack-name "$stack" --region "$AWS_REGION" &> /dev/null; then
            echo "  Waiting for $stack..."
            aws cloudformation wait stack-delete-complete \
                --stack-name "$stack" \
                --region "$AWS_REGION" 2>/dev/null && \
                echo "  ✓ $stack deleted" || \
                echo "  ✗ Timeout or error deleting $stack"
        fi
    done
    
    log_success "CloudFormation stacks deleted"
}

# Delete CloudWatch log groups
delete_log_groups() {
    log_info "Deleting CloudWatch log groups..."
    
    LOG_GROUPS=$(aws logs describe-log-groups \
        --log-group-name-prefix "/aws/lambda/ITOps-" \
        --query 'logGroups[].logGroupName' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)
    
    if [ ! -z "$LOG_GROUPS" ]; then
        for log_group in $LOG_GROUPS; do
            aws logs delete-log-group \
                --log-group-name "$log_group" \
                --region "$AWS_REGION" 2>/dev/null && \
                echo "  ✓ Deleted log group: $log_group" || \
                echo "  ✗ Failed to delete: $log_group"
        done
    else
        echo "  ✗ No log groups found"
    fi
    
    log_success "CloudWatch log groups deleted"
}

# Main cleanup
main() {
    delete_lambda_functions
    echo ""
    delete_step_functions
    echo ""
    delete_api_gateway
    echo ""
    delete_s3_buckets
    echo ""
    delete_log_groups
    echo ""
    delete_cloudformation_stacks
    
    echo ""
    echo -e "${GREEN}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║              CLEANUP COMPLETE                             ║
╚═══════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    echo -e "${YELLOW}All resources have been deleted.${NC}"
    echo -e "${YELLOW}Note: Some resources may take a few minutes to fully delete.${NC}\n"
    
    # Remove deployment info file
    if [ -f "deployment-info.txt" ]; then
        rm deployment-info.txt
        echo -e "Removed deployment-info.txt\n"
    fi
}

main

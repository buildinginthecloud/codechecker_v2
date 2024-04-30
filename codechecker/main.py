import os
import json
from aws_cdk import (
    Stack,
    aws_codecommit,
    aws_codebuild,
    aws_ec2,
    aws_events,
    aws_events_targets,
    aws_lambda,
    aws_sns,
    custom_resources,
)
from constructs import Construct
from aws_cdk import aws_iam


class CodeChecker(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        approvals_per_branch: dict,
        repository: aws_codecommit.IRepository = None,
        topic: aws_sns.ITopic = None,
        vpc: aws_ec2.IVpc = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not repository:
            repository = aws_codecommit.Repository(
                self, "codechecker-demo", repository_name="codechecker-demo"
            )
        if not topic:
            topic = aws_sns.Topic(self, "codechecker-demo-topic")

        # Create a lambda which will publish the codebuild result to codecommit
        publish_codebuild_result_lambda = aws_lambda.Function(
            self,
            "PullRequestPublishCodeBuildResult",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            handler="publish_codebuild_result.lambda_handler",
            code=aws_lambda.Code.from_asset("assets"),
            vpc=vpc,
            vpc_subnets=(
                None
                if vpc == None
                else aws_ec2.SubnetSelection(
                    subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED
                )
            ),
        )
        # Add rights to publish comments on PR
        repository.grant(publish_codebuild_result_lambda, "codecommit:PostCommentReply")
        repository.grant(
            publish_codebuild_result_lambda, "codecommit:PostCommentForPullRequest"
        )

        # Starting for loop over dict and create approval templates
        for branch, required_approvals in approvals_per_branch.items():
            # Create a CodeBuild project which will check the code on a pull request.
            pullrequest_project = aws_codebuild.Project(
                self,
                f"PullRequestCheckFor{branch}",
                source=aws_codebuild.Source.code_commit(repository=repository),
                environment=aws_codebuild.BuildEnvironment(
                    build_image=aws_codebuild.LinuxBuildImage.STANDARD_7_0
                ),
                build_spec=aws_codebuild.BuildSpec.from_object_to_yaml(
                    {
                        "version": "0.2",
                        "env": {"git-credential-helper": "yes"},
                        "phases": {
                            "install": {
                                "commands": [
                                    "npm install -g aws-cdk",
                                    "pip install git-remote-codecommit",
                                    "pip install -r requirements.txt",
                                ]
                            },
                            "build": {
                                "commands": [
                                    "cdk synth",
                                ]
                            },
                            "post_build": {
                                "commands": [
                                    "pytest --junitxml=reports/codechecker-pytest.xml > pytest-output.txt",
                                    'if grep -i "passed" pytest-output.txt; then PYTEST_RESULT="PASSED"; else PYTEST_RESULT="FAILED"; fi',
                                    'if [ $PYTEST_RESULT != "PASSED" ]; then PR_STATUS="REVOKE"; else PR_STATUS="APPROVE"; fi',
                                    "echo $PR_STATUS",
                                    "REVISION_ID=$(aws codecommit get-pull-request --pull-request-id $PULL_REQUEST_ID | jq -r '.pullRequest.revisionId')",
                                    "aws codecommit update-pull-request-approval-state --pull-request-id $PULL_REQUEST_ID --revision-id $REVISION_ID --approval-state $PR_STATUS --region $AWS_REGION",
                                ]
                            },
                        },
                        "reports": {
                            "pytest_reports": {
                                "files": ["codechecker-pytest.xml"],
                                "base-directory": "reports",
                                "file-format": "JUNITXML",
                            }
                        },
                    }
                ),
                vpc=vpc,
                subnet_selection=(
                    None
                    if vpc == None
                    else aws_ec2.SubnetSelection(
                        subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED
                    )
                ),
            )

            template = {
                "Version": "2018-11-08",
                "DestinationReferences": [f"refs/heads/{branch}"],
                "Statements": [
                    {
                        "Type": "Approvers",
                        "NumberOfApprovalsNeeded": required_approvals,
                        "ApprovalPoolMembers": [
                            f"arn:aws:sts::{Stack.of(self).account}:assumed-role/aacb-developer/*",
                            f"arn:aws:sts::{Stack.of(self).account}:assumed-role/{pullrequest_project.role}/*",
                        ],
                    }
                ],
            }
            json_string = json.dumps(template)
            create_approval_template = custom_resources.AwsCustomResource(
                self,
                f"CreateApprovalTemplateFor{branch}",
                on_create=custom_resources.AwsSdkCall(
                    service="CodeCommit",
                    action="createApprovalRuleTemplate",
                    physical_resource_id=custom_resources.PhysicalResourceId.of(
                        f"{str(required_approvals)}-approval-for-{repository.repository_name}-{branch}"
                    ),
                    parameters={
                        "approvalRuleTemplateName": f"{str(required_approvals)}-approval-for-{repository.repository_name}-{branch}",
                        "approvalRuleTemplateDescription": f"Requires {required_approvals} approvals from the team to approve the pull request",
                        "approvalRuleTemplateContent": json_string,
                    },
                ),
                on_update=custom_resources.AwsSdkCall(
                    service="CodeCommit",
                    action="updateApprovalRuleTemplateContent",
                    parameters={
                        "approvalRuleTemplateName": f"{str(required_approvals)}-approval-for-{repository.repository_name}-{branch}",
                        "newRuleContent": json_string,
                    },
                ),
                on_delete=custom_resources.AwsSdkCall(
                    service="CodeCommit",
                    action="deleteApprovalRuleTemplate",
                    parameters={
                        "approvalRuleTemplateName": f"{str(required_approvals)}-approval-for-{repository.repository_name}-{branch}"
                    },
                ),
                policy=custom_resources.AwsCustomResourcePolicy.from_sdk_calls(
                    resources=custom_resources.AwsCustomResourcePolicy.ANY_RESOURCE
                ),
                vpc=vpc,
                vpc_subnets=(
                    None
                    if vpc == None
                    else aws_ec2.SubnetSelection(
                        subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED
                    )
                ),
            )
            associate_approval_template = custom_resources.AwsCustomResource(
                self,
                f"AssociateApprovalTemplateFor{branch}",
                on_create=custom_resources.AwsSdkCall(
                    service="CodeCommit",
                    action="associateApprovalRuleTemplateWithRepository",
                    physical_resource_id=custom_resources.PhysicalResourceId.of(
                        f"{str(required_approvals)}-approval-for-{repository.repository_name}-{branch}-association"
                    ),
                    parameters={
                        "approvalRuleTemplateName": f"{str(required_approvals)}-approval-for-{repository.repository_name}-{branch}",
                        "repositoryName": repository.repository_name,
                    },
                ),
                on_delete=custom_resources.AwsSdkCall(
                    service="CodeCommit",
                    action="disassociateApprovalRuleTemplateFromRepository",
                    parameters={
                        "approvalRuleTemplateName": f"{str(required_approvals)}-approval-for-{repository.repository_name}-{branch}",
                        "repositoryName": repository.repository_name,
                    },
                ),
                policy=custom_resources.AwsCustomResourcePolicy.from_sdk_calls(
                    resources=custom_resources.AwsCustomResourcePolicy.ANY_RESOURCE
                ),
                vpc=vpc,
                vpc_subnets=(
                    None
                    if vpc == None
                    else aws_ec2.SubnetSelection(
                        subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED
                    )
                ),
            )
            pullrequest_project.add_to_role_policy(
                aws_iam.PolicyStatement(
                    actions=[
                        "codecommit:CreatePullRequestApprovalRule",
                        "codecommit:GetPullRequest",
                        "codecommit:PostCommentForPullRequest",
                        "codecommit:UpdatePullRequestApprovalState",
                    ],
                    resources=[repository.repository_arn],
                )
            )

            create_approval_template.node.add_dependency(pullrequest_project)
            associate_approval_template.node.add_dependency(create_approval_template)

            pull_request_rule = aws_events.Rule(
                self,
                f"OnPullRequest{branch}EventRule",
                event_pattern=aws_events.EventPattern(
                    source=["aws.codecommit"],
                    resources=[repository.repository_arn],
                    detail={
                        "event": [
                            "pullRequestCreated",
                            "pullRequestSourceBranchUpdated",
                        ]
                    },
                ),
            )

            pull_request_rule.add_target(
                target=aws_events_targets.CodeBuildProject(
                    pullrequest_project,
                    event=aws_events.RuleTargetInput.from_object(
                        {
                            "sourceVersion": aws_events.EventField.from_path(
                                "$.detail.sourceCommit"
                            ),
                            "environmentVariablesOverride": [
                                {
                                    "name": "DESTINATION_COMMIT_ID",
                                    "type": "PLAINTEXT",
                                    "value": aws_events.EventField.from_path(
                                        "$.detail.destinationCommit"
                                    ),
                                },
                                {
                                    "name": "PULL_REQUEST_ID",
                                    "type": "PLAINTEXT",
                                    "value": aws_events.EventField.from_path(
                                        "$.detail.pullRequestId"
                                    ),
                                },
                                {
                                    "name": "SOURCE_COMMIT_ID",
                                    "type": "PLAINTEXT",
                                    "value": aws_events.EventField.from_path(
                                        "$.detail.sourceCommit"
                                    ),
                                },
                                {
                                    "name": "REPOSITORY_NAME",
                                    "type": "PLAINTEXT",
                                    "value": aws_events.EventField.from_path(
                                        "$.detail.repositoryNames[0]"
                                    ),
                                },
                            ],
                        }
                    ),
                )
            )
            pullrequest_project.on_state_change(
                "PullRequestBuildStateChange",
                target=aws_events_targets.LambdaFunction(
                    publish_codebuild_result_lambda
                ),
            )
            # Send failed build notification to SNS topic
            pullrequest_project.on_build_failed(
                "OnBuildFailed",
                target=aws_events_targets.SnsTopic(topic=topic),
            )

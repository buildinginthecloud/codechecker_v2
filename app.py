import os
from aws_cdk import App, Environment
from codechecker.main import CodeChecker

# for development, use account/region from cdk cli
dev_env = Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=os.getenv("CDK_DEFAULT_REGION")
)

app = App()

CodeChecker(
    app,
    "codechecker-dev",
    env=dev_env,
    approvals_per_branch={"main": 2},
)
# MyStack(app, "codechecker-prod", env=prod_env)

app.synth()

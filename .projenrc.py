from projen.awscdk import AwsCdkPythonApp

project = AwsCdkPythonApp(
    author_email="no-reply@dontsendmemails.com",
    author_name="Yvo van Zee",
    cdk_version="2.138.0",
    module_name="codechecker",
    name="codechecker",
    version="0.1.0",
    deps=["boto3==1.34.94"],
)

project.synth()

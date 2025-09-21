{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Principal": {
        "Federated": "arn:aws:iam::aws:policy/aws:github:actions"
      },
      "Condition": {
        "StringEquals": {
          "oidc.github.com:sub": "repo:your-org/your-repo:ref:refs/heads/main",  // Only allow 'main' branch
          "oidc.github.com:workflow": "DeployToProduction"  // Only allow 'DeployToProduction' workflow
        }
      }
    }
  ]
}


{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<AWS_ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:<YOUR_ORGANIZATION>/<YOUR_REPOSITORY>:ref:refs/heads/main"
        }
      }
    }
  ]
}


{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Principal": {
        "Federated": "arn:aws:iam::<AWS_ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:<YOUR_ORGANIZATION>/<YOUR_REPOSITORY>:ref:refs/heads/main"
        },
        "ForAllValues:StringEquals": {
          "token.actions.githubusercontent.com:job_workflow_ref": "DeployToProduction"
        }
      }
    }
  ]
}

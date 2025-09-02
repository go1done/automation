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

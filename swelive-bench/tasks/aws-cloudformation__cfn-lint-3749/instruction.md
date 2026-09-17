Fn::ForEach could not be resolved when values array references Map using AccountId key
### CloudFormation Lint Version

cfn-lint 1.16.1 / git v1.16.1-5-g07652d4a4

### What operating system are you using?

Mac

### Describe the bug

`cfn-lint` fails to resolve `Fn::ForEach` when values array comes from Map with `AccountId` key

```
$ cfn-lint mapt.yaml 
E0001 Error transforming template: Fn::ForEach could not be resolved
mapt.yaml:11:7
```

### Expected behavior

cfn-lint passes

### Reproduction template

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::LanguageExtensions
Mappings:
  AccountMap:
    12345678901:
      Emails:
        - test@test.com
Resources:
  'Fn::ForEach::Subscriptions':
    - Email
    - !FindInMap [AccountMap, !Ref AWS::AccountId, Emails]
    - 'SubscriptionFor&{Email}':
        Type: AWS::SNS::Subscription
        Properties:
          TopicArn: "arn:aws:sns:us-east-1:12345678901:my-sns-topic"
          Protocol: email
          Endpoint: !Ref Email
```

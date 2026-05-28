pipeline {
  agent any

  environment {
    ECR_REGISTRY      = credentials('ECR_REGISTRY')
    SLACK_WEBHOOK_URL = credentials('SLACK_WEBHOOK_URL')
    IAM_ROLE_ARN      = credentials('IAM_ROLE_ARN')
    AWS_REGION        = 'ap-northeast-2'
    EKS_CLUSTER_NAME  = 'patrasche-news'
    IMAGE_TAG         = 'latest'
  }

  stages {

    stage('Gitleaks 보안 스캔') {
      steps {
        sh 'gitleaks detect --source . --exit-code 1'
      }
    }

    stage('Trivy 보안 스캔') {
      steps {
        sh '''
          mkdir -p /tmp/trivy-temp
          trivy fs . \
            --severity HIGH,CRITICAL \
            --exit-code 1 \
            --cache-dir /tmp/trivy-temp
        '''
      }
    }

    // stage('린트 검사') {
    //   steps {
    //     sh '''
    //       pip3 install flake8
    //       /var/lib/jenkins/.local/bin/flake8 backend/mail-service --max-line-length=100
    //       /var/lib/jenkins/.local/bin/flake8 backend/news-fetcher-service --max-line-length=100
    //       /var/lib/jenkins/.local/bin/flake8 backend/news-summarizer-service --max-line-length=100
    //       /var/lib/jenkins/.local/bin/flake8 backend/user-service --max-line-length=100
    //     '''
    //   }
    // }

    // stage('테스트') {
    //   environment {
    //     DB_URL           = credentials('DB_URL')
    //     SMTP_HOST        = credentials('SMTP_HOST')
    //     SMTP_PORT        = credentials('SMTP_PORT')
    //     SMTP_USER        = credentials('SMTP_USER')
    //     SMTP_PASS        = credentials('SMTP_PASS')
    //     ENABLE_SCHEDULER = 'false'
    //   }
    //   steps {
    //     sh '''
    //       PYTEST=/var/lib/jenkins/.local/bin/pytest
    //       pip3 install anyio[trio]

    //       pip3 install -r backend/mail-service/requirements.txt
    //       cd backend/mail-service && $PYTEST tests/ -v && cd ../..

    //       pip3 install -r backend/news-fetcher-service/requirements.txt
    //       cd backend/news-fetcher-service && $PYTEST tests/ -v && cd ../..

    //       pip3 install -r backend/news-summarizer-service/requirements.txt
    //       cd backend/news-summarizer-service && $PYTEST tests/ -v && cd ../..

    //       pip3 install -r backend/user-service/requirements.txt
    //       cd backend/user-service && $PYTEST tests/ -v && cd ../..
    //     '''
    //   }
    // }

    // 도커 빌드 & ECR 푸시는 인프라 레포 Jenkinsfile에서 전담

    // ──────────────────────────────────────────────────────────
    // Ansible 배포 전 Assume Role (kubectl 실행에 AWS 권한 필요)
    // ──────────────────────────────────────────────────────────
    stage('AWS Assume Role') {
      steps {
        script {
          assumeAwsRole('jenkins-app-deploy-session')
        }
      }
    }

    stage('Ansible 배포') {
      steps {
        sh '''
          aws eks update-kubeconfig --name $EKS_CLUSTER_NAME --region $AWS_REGION

          ansible-playbook \
            -i ansible/inventory.ini \
            ansible/deploy.yml \
            --extra-vars "image_tag=$IMAGE_TAG ecr_registry=$ECR_REGISTRY"
        '''
      }
    }
  }

  post {
    success {
      sh '''
        curl -X POST "$SLACK_WEBHOOK_URL" \
        -H 'Content-type: application/json' \
        -d '{"text":"✅ *[patrasche-app]* 배포 완료!"}'
      '''
    }
    failure {
      sh '''
        curl -X POST "$SLACK_WEBHOOK_URL" \
        -H 'Content-type: application/json' \
        -d '{"text":"❌ *[patrasche-app]* 배포 실패!\n확인 필요"}'
      '''
    }
  }
}

// ──────────────────────────────────────────────────────────
// 공통 함수: AWS Assume Role
// ──────────────────────────────────────────────────────────
def assumeAwsRole(String sessionName) {
  withCredentials([
    string(credentialsId: 'AWS_ACCESS_KEY_ID', variable: 'BASE_KEY'),
    string(credentialsId: 'AWS_SECRET_ACCESS_KEY', variable: 'BASE_SECRET')
  ]) {
    def credsStr = sh(script: """
      AWS_ACCESS_KEY_ID=\$BASE_KEY \
      AWS_SECRET_ACCESS_KEY=\$BASE_SECRET \
      AWS_SESSION_TOKEN="" \
      aws sts assume-role \
        --role-arn "${env.IAM_ROLE_ARN}" \
        --role-session-name "${sessionName}" \
        --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
        --output text
    """, returnStdout: true).trim()

    def credsList = credsStr.tokenize()

    if (credsList.size() < 3) {
      error "AssumeRole failed: STS credentials were not returned"
    }

    env.AWS_ACCESS_KEY_ID     = credsList[0]
    env.AWS_SECRET_ACCESS_KEY = credsList[1]
    env.AWS_SESSION_TOKEN     = credsList[2]

    echo "AWS_ACCESS_KEY_ID exists? ${env.AWS_ACCESS_KEY_ID ? 'YES' : 'NO'}"
    echo "AWS_SESSION_TOKEN exists? ${env.AWS_SESSION_TOKEN ? 'YES' : 'NO'}"

    sh '''
      set -eu
      IDENTITY_ARN=$(aws sts get-caller-identity --query Arn --output text)
      echo "Current AWS Identity: $IDENTITY_ARN"
      case "$IDENTITY_ARN" in
        *":assumed-role/jenkins-onprem-deploy-role/"*)
          echo "OK: assumed deploy role"
          ;;
        *)
          echo "ERROR: not using deploy role. Current identity: $IDENTITY_ARN"
          exit 1
          ;;
      esac
    '''
  }
}

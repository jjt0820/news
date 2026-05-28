pipeline {
  agent any

  environment {
    ECR_REGISTRY      = credentials('ECR_REGISTRY')
    SLACK_WEBHOOK_URL = credentials('SLACK_WEBHOOK_URL')
    AWS_ACCESS_KEY_ID = credentials('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = credentials('AWS_SECRET_ACCESS_KEY')
    IMAGE_TAG         = "${GIT_COMMIT}"
    IAM_ROLE_ARN      = credentials('IAM_ROLE_ARN')
  }

  stages {

    stage('Gitleaks 보안 스캔') {
      steps {
        sh 'gitleaks detect --source . --exit-code 1'
      }
    }

    stage('Trivy 보안 스캔') {
      steps {
        sh 'trivy fs . --severity HIGH,CRITICAL --exit-code 1'
      }
    }

    stage('린트 검사') {
      steps {
        sh '''
          pip3 install flake8
          /var/lib/jenkins/.local/bin/flake8 backend/mail-service --max-line-length=100
          /var/lib/jenkins/.local/bin/flake8 backend/news-fetcher-service --max-line-length=100
          /var/lib/jenkins/.local/bin/flake8 backend/news-summarizer-service --max-line-length=100
          /var/lib/jenkins/.local/bin/flake8 backend/user-service --max-line-length=100
        '''
      }
    }

    stage('테스트') {
      environment {
        DB_URL           = credentials('DB_URL')
        SMTP_HOST        = credentials('SMTP_HOST')
        SMTP_PORT        = credentials('SMTP_PORT')
        SMTP_USER        = credentials('SMTP_USER')
        SMTP_PASS        = credentials('SMTP_PASS')
        ENABLE_SCHEDULER = 'false'
      }
      steps {
        sh '''
          PYTEST=/var/lib/jenkins/.local/bin/pytest
          pip3 install anyio[trio]

          pip3 install -r backend/mail-service/requirements.txt
          cd backend/mail-service && $PYTEST tests/ -v && cd ../..

          pip3 install -r backend/news-fetcher-service/requirements.txt
          cd backend/news-fetcher-service && $PYTEST tests/ -v && cd ../..

          pip3 install -r backend/news-summarizer-service/requirements.txt
          cd backend/news-summarizer-service && $PYTEST tests/ -v && cd ../..

          pip3 install -r backend/user-service/requirements.txt
          cd backend/user-service && $PYTEST tests/ -v && cd ../..
        '''
      }
    }

    // 도커 빌드 & ECR 푸시는 인프라 레포 Jenkinsfile에서 전담

    stage('Ansible 배포') {
      steps {
        sh '''
          ansible-playbook \
            -i ansible/inventory.ini \
            ansible/deploy.yml \
            --extra-vars "image_tag=$IMAGE_TAG ecr_registry=$ECR_REGISTRY iam_role_arn=$IAM_ROLE_ARN"
        '''
      }
    }
  }

  post {
    success {
      sh '''
        curl -X POST $SLACK_WEBHOOK_URL \
        -H 'Content-type: application/json' \
        -d '{"text":"✅ *[patrasche-app]* 배포 완료!\n커밋: $IMAGE_TAG"}'
      '''
    }
    failure {
      sh '''
        curl -X POST $SLACK_WEBHOOK_URL \
        -H 'Content-type: application/json' \
        -d '{"text":"❌ *[patrasche-app]* 배포 실패!\n확인 필요"}'
      '''
    }
  }
}

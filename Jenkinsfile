pipeline {
  agent any


  //환경변수 설정
  environment {
    ECR_REGISTRY = credentials('ECR_REGISTRY')
    SLACK_WEBHOOK_URL = credentials('SLACK_WEBHOOK_URL')
    IMAGE_TAG = "${GIT_COMMIT}"
  }
  //실행할 단계들
  //민감정보 스캔
  stages {
    stage('Gitleaks 보안 스캔') {
      steps {
        sh 'gitleaks detect --source . --exit-code 1'
      } // --exit-code 1 -> 발견 시 파이프라인 실패
    }

    stage('Trivy 보안 스캔') {
      steps {
        //셸 명령어 실행
        sh ' trivy fs ./backend --severity HIGH,CRITICAL --exit-code 1'
        
      } //trivy fs -> 파일시스템 스캔
        //--severity HIGH,CRITICAL -> 높은 취약점만
        //--exit-code 1 -> 발견 시 실패
    }

    //flake8 = Python 코드 스타일 검사(서비스 3개 각각 검사)
    stage('린트 검사') {
      steps {
        sh '''
          pip3 install flake8
          /var/lib/jenkins/.local/bin/flake8 backend/mail-service --max-line-length=100
          /var/lib/jenkins/.local/bin/flake8 backend/news-service --max-line-length=100
          /var/lib/jenkins/.local/bin/flake8 backend/user-service --max-line-length=100
        '''
      }
    }
    //pytest = Python 테스트 실행(서비스 3개 각각 검사)
    // stage('테스트') {
    //   steps {
    //     sh '''
    //       pip3 install pytest
    //       /var/lib/jenkins/.local/bin/pytest backend/mail-service/tests/ -v
    //       /var/lib/jenkins/.local/bin/pytest backend/news-service/tests/ -v
    //       /var/lib/jenkins/.local/bin/pytest backend/user-service/tests/ -v
    //     '''
    //   }
    // }

    stage('도커 빌드 & ECR 푸시') {
      steps {
        sh '''
          aws ecr get-login-password --region ap-northeast-2 | docker login --username AWS --password-stdin $ECR_REGISTRY
          docker build -t $ECR_REGISTRY/patrasche-notifier:$IMAGE_TAG ./backend/mail-service
          docker push $ECR_REGISTRY/patrasche-notifier:$IMAGE_TAG
          docker build -t $ECR_REGISTRY/patrasche-crawler:$IMAGE_TAG ./backend/news-service
          docker push $ECR_REGISTRY/patrasche-crawler:$IMAGE_TAG
          docker build -t $ECR_REGISTRY/patrasche-analyzer:$IMAGE_TAG ./backend/news-service
          docker push $ECR_REGISTRY/patrasche-analyzer:$IMAGE_TAG
          docker build -t $ECR_REGISTRY/patrasche-backend:$IMAGE_TAG ./backend/user-service
          docker push $ECR_REGISTRY/patrasche-backend:$IMAGE_TAG
        '''
      } // ECR 로그인
            // ->서비스별 이미지 빌드
            // ->ECR에 push (총 4개 이미지)

    }

    stage('Ansible 배포') {
      steps {
        sh '''
          ansible-playbook \
            -i ansible/inventory.ini \
            ansible/deploy.yml \
            --extra-vars "image_tag=$IMAGE_TAG"
        '''
      } //ansible-playbook = 플레이북 실행
        // -i inventory.ini = 대상 서버 목록
        // deploy.yml = 배포 스크립트
        // --extra-vars = 커밋 해시 전달
    }
  }

  //완료 후 처리
//   post {
//     success {
//       sh '''
//         curl -X POST $SLACK_WEBHOOK_URL \
//         -H 'Content-type: application/json' \
//         -d '{"text":"✅ *[patrasche]* 배포 완료!\n커밋: $IMAGE_TAG\n작업자: $GIT_COMMITTER_NAME"}'
//       '''
//     }
//     failure {
//       sh '''
//         curl -X POST $SLACK_WEBHOOK_URL \
//         -H 'Content-type: application/json' \
//         -d '{"text":"❌ *[patrasche]* 배포 실패!\n확인 필요"}'
//       '''
//     }
//   }
}
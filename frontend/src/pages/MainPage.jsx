import { useEffect, useState } from 'react'
import styles from './MainPage.module.css'

const TABS = [
  { emoji: '💻', name: 'IT/테크', value: 'tech' },
  { emoji: '📈', name: '경제',   value: 'economy' },
  { emoji: '🌍', name: '국제',   value: 'world' },
  { emoji: '⚽', name: '스포츠', value: 'sports' },
]

export default function MainPage() {
  const [activeTab, setActiveTab] = useState('tech') 
  const [news, setNews] = useState([])

  // TODO: API 서버 주소 확정되면 앞에 주소 추가
  // 예) http://ALB주소/api/news/list?category=tech
  useEffect(()=> {
    fetch(`cogez-alb-518575871.ap-northeast-2.elb.amazonaws.com/api/news/list?category=${activeTab}`)
      .then(res => res.json())
      .then(data => setNews(data))
      .catch(err => {
        console.error(err)
        setNews([]) // 에러나면 빈 배열
      })
  }, [activeTab])

  return (
    <div>
      <div className={styles.header}>
        <div className={styles.greeting}>오늘의 뉴스</div>
        <div className={styles.title}>
          좋은 아침이에요,<br /><em>큐레이션 뉴스</em>가 도착했어요
        </div>
      </div>

      <div className={styles.tabs}>
        {TABS.map(tab => (
          <button
            key={tab.value}
            className={`${styles.tab} ${activeTab === tab.value ? styles.active : ''}`}
            onClick={() => setActiveTab(tab.value)}
          >
            {tab.emoji} {tab.name}
          </button>
        ))}
      </div>

      <div className={styles.list}>
        {news.length === 0 ? (
          <div className={styles.empty}>
            <span>📭</span>
            <p>아직 뉴스가 없어요</p>
          </div>
        ) : (
          news.map((item, i) => (
            <div key={i} className={styles.card}>
              <div className={styles.meta}>
                <span className={styles.source}>{item.source}</span>
                <span className={styles.dot} />
                <span className={styles.time}>{item.time}</span>
              </div>
              <div className={styles.newsTitle}>{item.title}</div>
              <div className={styles.desc}>{item.desc}</div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
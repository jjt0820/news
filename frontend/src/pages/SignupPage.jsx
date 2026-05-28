import { useState } from 'react'
import styles from './SignupPage.module.css'

const CATEGORIES = [
  { emoji: '💻', name: 'IT/테크', value: 'tech' },
  { emoji: '📈', name: '경제',   value: 'economy' },
  { emoji: '🌍', name: '국제',   value: 'world' },
  { emoji: '⚽', name: '스포츠', value: 'sports' },
  { emoji: '🎬', name: '연예',   value: 'entertainment' },
  { emoji: '🏛️', name: '정치',   value: 'politics' },
]

export default function SignupPage({ onSignup }) {
  const [email, setEmail] = useState('') //입력한 이메일 저장
  const [selected, setSelected] = useState(['tech']) // 선택된 카테고리 목록 (기본값: tech)

  const toggleCategory = (value) => {
    setSelected(prev =>
      prev.includes(value)
        ? prev.filter(v => v !== value) // 이미 선택됨 -> 제거
        : [...prev, value] // 선택안됨 -> 추가
    )
  }

  const handleSubmit = async() => {
    if (!email) return alert('이메일을 입력해주세요')
    if (selected.length === 0) return alert('카테고리를 하나 이상 선택해주세요')
    
    try {
      const response = await fetch('cogez-alb-518575871.ap-northeast-2.elb.amazonaws.com', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, categories: selected })
      })
      if (response.ok) {
        onSignup()
      }
    } catch (error) {
      alert('구독 신청 중 오류가 발생했습니다')
    }
  
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>NewsFlow</div>
      <h1 className={styles.title}>
        나만의 <em>뉴스</em>를<br />매일 아침 받아보세요
      </h1>
      <p className={styles.sub}>
        관심 분야를 선택하면 매일 정해진 시간에<br />
        큐레이션된 뉴스를 이메일로 보내드립니다.
      </p>

      <div className={styles.fieldGroup}>
        <div className={styles.label}>이메일 주소</div>
        <input
          className={styles.input}
          type="email"
          placeholder="example@email.com"
          value={email}
          onChange={e => setEmail(e.target.value)}
        />
      </div>

      <div className={styles.label}>관심 카테고리 선택 (복수 선택 가능)</div>
      <div className={styles.grid}>
        {CATEGORIES.map(cat => (
          <div
            key={cat.value}
            className={`${styles.chip} ${selected.includes(cat.value) ? styles.selected : ''}`}
            onClick={() => toggleCategory(cat.value)}
          >
            <span className={styles.emoji}>{cat.emoji}</span>
            <span className={styles.chipName}>{cat.name}</span>
          </div>
        ))}
      </div>

      <button className={styles.btn} onClick={handleSubmit}>
        구독 시작하기
      </button>
      <p className={styles.note}>
        비밀번호 없이 이메일만으로 구독할 수 있어요<br />
        언제든지 구독을 취소할 수 있습니다
      </p>
    </div>
  )
}
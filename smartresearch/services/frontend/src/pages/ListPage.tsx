import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchWSIList } from '../api'

export default function ListPage() {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>()

  useEffect(() => {
    fetchWSIList()
      .then((d) => setItems(d.items || []))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={styles.container}>Loading...</div>
  if (error)   return <div style={styles.container}>Error: {error}</div>
  if (!items.length) return <div style={styles.container}>No WSI found. Please ingest data first.</div>

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>WSI List</h1>
          <p style={styles.subtitle}>Total {items.length} slides</p>
        </div>
        <Link to="/" style={styles.homeLink}>
          <button style={styles.homeButton}>← Back to Dashboard</button>
        </Link>
      </div>

      <div style={styles.container}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>WSI ID</th>
              <th style={styles.th}>Label</th>
              <th style={styles.th}>Action</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.wsi_id}>
                <td style={styles.td}>{it.wsi_id}</td>
                <td style={styles.td}>{it.label || '-'}</td>
                <td style={styles.td}>
                  <Link to={`/wsi/${encodeURIComponent(it.wsi_id)}`}>
                    <button style={styles.button}>View</button>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const styles = {
  page: {
    minHeight: '100vh',
    background: '#f6f8fa'
  },
  header: {
    background: 'white',
    padding: 24,
    marginBottom: 20,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center'
  },
  title: {
    margin: 0,
    fontSize: 28,
    fontWeight: 'bold' as const,
    color: '#333'
  },
  subtitle: {
    margin: '8px 0 0 0',
    fontSize: 14,
    color: '#666'
  },
  homeLink: {
    textDecoration: 'none'
  },
  homeButton: {
    padding: '10px 20px',
    cursor: 'pointer',
    background: 'white',
    color: '#333',
    border: '2px solid #d0d7de',
    borderRadius: 6,
    fontSize: 14,
    fontWeight: 'bold' as const
  },
  container: {
    padding: '0 20px 20px 20px',
    maxWidth: 1200,
    margin: '0 auto'
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    background: 'white',
    borderRadius: 8,
    overflow: 'hidden',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
  },
  th: {
    border: '1px solid #ddd',
    padding: 12,
    background: '#f6f8fa',
    textAlign: 'left' as const,
    fontWeight: 'bold' as const
  },
  td: {
    border: '1px solid #ddd',
    padding: 12
  },
  button: {
    padding: '6px 12px',
    cursor: 'pointer',
    background: '#0969da',
    color: 'white',
    border: 'none',
    borderRadius: 4,
    fontWeight: 'bold' as const
  }
}


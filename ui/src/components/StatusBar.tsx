import type { Status } from '../App'

const labels: Record<Status, string> = {
  idle:      'STANDBY',
  listening: 'LISTENING',
  thinking:  'PROCESSING',
  speaking:  'SPEAKING',
}

export default function StatusBar({ status }: { status: Status }) {
  return (
    <div className="status-bar">
      <div className={`status-dot ${status}`} />
      CORTANA / {labels[status]}
    </div>
  )
}

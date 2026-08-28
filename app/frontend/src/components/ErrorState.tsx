import TriangleAlert from 'lucide-react/dist/esm/icons/triangle-alert'

export interface ErrorStateProps {
  code?: string
  message?: string
  onRetry?: () => void
}

export default function ErrorState({ code, message, onRetry }: ErrorStateProps) {
  return (
    <section className="statePanel" aria-label="错误状态">
      <TriangleAlert size={32} aria-hidden="true" className="stateIconError" />
      <p className="stateTitle">加载失败</p>
      <p className="stateHint">{message || '网络请求未能成功，请稍后重试。'}</p>
      {onRetry && (
        <button type="button" className="secondaryButtonSmall" onClick={onRetry} data-testid="error-retry">
          重试
        </button>
      )}
      {code ? <p className="stateAux">错误码：{code}</p> : null}
    </section>
  )
}

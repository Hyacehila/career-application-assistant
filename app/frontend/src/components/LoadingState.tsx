const SKELETON_ROWS = Array.from({ length: 4 }, (_, index) => index)

export default function LoadingState() {
  return (
    <section className="loadingPanel" aria-label="加载中">
      <p className="loadingText">
        正在加载投递记录…
      </p>
      <div className="loadingList" aria-hidden="true">
        {SKELETON_ROWS.map((row) => (
          <div key={row} className="loadingCard">
            <div className="loadingBarWide" />
            <div className="loadingBarNarrow" />
          </div>
        ))}
      </div>
    </section>
  )
}
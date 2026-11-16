import styles from './Chart.module.css';

/** The tabular alternative for a chart or map (design.md A.15, 15.8). */
export function DataTable({ caption, columns, rows, numericFrom = 1 }: { caption: string; columns: string[]; rows: (string | number)[][]; numericFrom?: number }) {
  return (
    <div className={styles.tableScroll}>
      <table className={styles.table}>
        <caption className={styles.caption}>{caption}</caption>
        <thead>
          <tr>{columns.map((c, i) => <th key={c} scope="col" data-num={i >= numericFrom || undefined}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((cell, j) => j === 0
                ? <th key={j} scope="row">{cell}</th>
                : <td key={j} data-num={j >= numericFrom || undefined} data-label={columns[j]}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

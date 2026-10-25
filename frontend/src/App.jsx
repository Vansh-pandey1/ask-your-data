import React, { useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip
} from 'recharts';
import './App.css';

export default function App() {
  const [dataset, setDataset] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [askError, setAskError] = useState(null);

  const [activeTab, setActiveTab] = useState('summary');
  const [showSql, setShowSql] = useState(true);

  // CSV File Upload Handler
  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError(null);
    setAnswer(null);
    setAskError(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Upload failed');
      }

      setDataset(data);
      setActiveTab('summary');
    } catch (err) {
      setUploadError(err.message);
      setDataset(null);
    } finally {
      setUploading(false);
    }
  };

  // Ask Question Handler
  const handleAsk = async (e) => {
    e?.preventDefault();
    if (!question.trim() || asking) return;

    setAsking(true);
    setAskError(null);

    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim(), row_limit: 100 }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to answer question');
      }

      if (data.error) {
        setAskError(data.error);
        setAnswer(null);
      } else {
        setAnswer(data);
      }
    } catch (err) {
      setAskError(err.message);
      setAnswer(null);
    } finally {
      setAsking(false);
    }
  };

  // Detect if query results are suitable for a bar chart
  const getChartConfig = (result) => {
    if (!result || !result.rows || result.rows.length === 0 || result.columns.length < 2) {
      return null;
    }
    // Limit to reasonable number of items for visual clarity
    if (result.rows.length > 25) {
      return null;
    }

    const firstRow = result.rows[0];
    let catKey = null;
    let numKey = null;

    for (const col of result.columns) {
      const val = firstRow[col];
      if (typeof val === 'number' && !numKey) {
        numKey = col;
      } else if ((typeof val === 'string' || typeof val === 'boolean') && !catKey) {
        catKey = col;
      }
    }

    if (catKey && numKey) {
      return { xKey: catKey, yKey: numKey };
    }
    return null;
  };

  const chartConfig = getChartConfig(answer);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-brand">
          <div className="logo-badge">SQL</div>
          <h1>Ask Your Data</h1>
        </div>
        {dataset && (
          <div className="dataset-badge">
            <span className="dataset-dot"></span>
            <strong>{dataset.file_name}</strong>
            <span className="dataset-meta">
              ({dataset.total_rows} rows &bull; {dataset.total_columns} columns)
            </span>
          </div>
        )}
      </header>

      {/* Main Content */}
      <main className="app-main">
        {/* Upload Section */}
        <section className="card upload-card">
          <div className="upload-header">
            <h2>{dataset ? 'Active Dataset' : 'Upload CSV Dataset'}</h2>
            {dataset && (
              <label className="btn-secondary file-label">
                Upload Different CSV
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  hidden
                />
              </label>
            )}
          </div>

          {!dataset && (
            <div className="dropzone">
              <label className="dropzone-label">
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  hidden
                />
                <div className="dropzone-icon">&uarr;</div>
                <div className="dropzone-text">
                  <strong>Click to upload</strong> or drag and drop a CSV
                </div>
                <div className="dropzone-sub">Max file size: 20MB &bull; Standard CSV format</div>
              </label>
            </div>
          )}

          {uploading && (
            <div className="alert alert-info">
              <span className="spinner"></span> Profiling dataset and ingesting into SQLite...
            </div>
          )}

          {uploadError && (
            <div className="alert alert-error">
              <strong>Error:</strong> {uploadError}
            </div>
          )}
        </section>

        {/* Dataset Summary & Preview Tabs */}
        {dataset && (
          <section className="card">
            <div className="tabs">
              <button
                className={`tab-btn ${activeTab === 'summary' ? 'active' : ''}`}
                onClick={() => setActiveTab('summary')}
              >
                Dataset Summary
              </button>
              <button
                className={`tab-btn ${activeTab === 'preview' ? 'active' : ''}`}
                onClick={() => setActiveTab('preview')}
              >
                Data Preview (First 5 Rows)
              </button>
            </div>

            {activeTab === 'summary' && (
              <div className="summary-tab">
                {/* Stat Tiles */}
                <div className="stat-grid">
                  <div className="stat-tile">
                    <div className="stat-label">Total Rows</div>
                    <div className="stat-value">{dataset.profile.total_rows}</div>
                  </div>
                  <div className="stat-tile">
                    <div className="stat-label">Total Columns</div>
                    <div className="stat-value">{dataset.profile.total_columns}</div>
                  </div>
                  <div className="stat-tile">
                    <div className="stat-label">Duplicate Rows</div>
                    <div className="stat-value">{dataset.profile.duplicate_row_count}</div>
                  </div>
                </div>

                {/* Column Breakdown Table */}
                <h3 className="section-title">Column Profiles</h3>
                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Type</th>
                        <th>Nulls (%)</th>
                        <th>Unique</th>
                        <th>Statistics / Values</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dataset.profile.columns.map((col) => (
                        <tr key={col.column_name}>
                          <td><strong>{col.column_name}</strong></td>
                          <td><span className="type-tag">{col.column_type}</span></td>
                          <td>{col.null_count} ({col.null_percentage}%)</td>
                          <td>{col.unique_count}</td>
                          <td className="stats-cell">
                            {col.numeric_stats && (
                              <span className="stat-detail">
                                min: {col.numeric_stats.min} &bull; max: {col.numeric_stats.max} &bull; mean: {col.numeric_stats.mean.toFixed(2)} &bull; median: {col.numeric_stats.median}
                              </span>
                            )}
                            {col.date_range && (
                              <span className="stat-detail">
                                range: {col.date_range.min_date} to {col.date_range.max_date}
                              </span>
                            )}
                            {col.categorical_stats && (
                              <span className="stat-detail">
                                top: {Object.entries(col.categorical_stats).map(([k, v]) => `${k} (${v})`).join(', ')}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeTab === 'preview' && (
              <div className="preview-tab">
                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        {dataset.column_names.map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {dataset.preview_rows.map((row, idx) => (
                        <tr key={idx}>
                          {dataset.column_names.map((col) => (
                            <td key={col}>
                              {row[col] !== null && row[col] !== undefined
                                ? String(row[col])
                                : <span className="null-val">null</span>}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        )}

        {/* Natural Language Question Section */}
        {dataset && (
          <section className="card">
            <h2 className="section-title">Ask a Question in Natural Language</h2>
            <form onSubmit={handleAsk} className="question-form">
              <input
                type="text"
                className="input-field"
                placeholder="e.g. What is the total sales for each product, sorted highest to lowest?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={asking}
              />
              <button
                type="submit"
                className="btn-primary"
                disabled={asking || !question.trim()}
              >
                {asking ? 'Generating SQL...' : 'Ask Data'}
              </button>
            </form>

            {asking && (
              <div className="alert alert-info">
                <span className="spinner"></span> LangGraph is generating SQL, validating read-only AST, and querying SQLite...
              </div>
            )}

            {askError && (
              <div className="alert alert-error">
                <strong>Query Error:</strong> {askError}
              </div>
            )}

            {/* Answer Display */}
            {answer && (
              <div className="answer-section">
                {/* Generated SQL Accordion */}
                <div className="sql-box">
                  <div
                    className="sql-box-header"
                    onClick={() => setShowSql(!showSql)}
                  >
                    <span>
                      <strong>Executed SQL:</strong> {showSql ? '▼' : '▶'}
                    </span>
                    {answer.correction_attempted && (
                      <span className="badge badge-warning">Auto-corrected (1 retry)</span>
                    )}
                  </div>
                  {showSql && (
                    <pre className="sql-code">
                      <code>{answer.generated_sql}</code>
                    </pre>
                  )}
                </div>

                {/* Optional Chart */}
                {chartConfig && (
                  <div className="chart-container">
                    <h3 className="section-title">
                      Visualization: {chartConfig.yKey} by {chartConfig.xKey}
                    </h3>
                    <div style={{ width: '100%', height: 320 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart
                          data={answer.rows}
                          margin={{ top: 20, right: 30, left: 20, bottom: 40 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                          <XAxis
                            dataKey={chartConfig.xKey}
                            tick={{ fontSize: 12, fill: '#4b5563' }}
                            angle={-20}
                            textAnchor="end"
                          />
                          <YAxis tick={{ fontSize: 12, fill: '#4b5563' }} />
                          <Tooltip
                            contentStyle={{
                              borderRadius: '6px',
                              border: '1px solid #e5e7eb',
                              boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
                            }}
                          />
                          <Bar
                            dataKey={chartConfig.yKey}
                            fill="#2563eb"
                            radius={[4, 4, 0, 0]}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Result Table */}
                <div className="results-container">
                  <h3 className="section-title">
                    Result Table ({answer.row_count} {answer.row_count === 1 ? 'row' : 'rows'})
                  </h3>
                  {answer.rows.length === 0 ? (
                    <div className="empty-results">No rows matched this query.</div>
                  ) : (
                    <div className="table-responsive">
                      <table className="data-table">
                        <thead>
                          <tr>
                            {answer.columns.map((col) => (
                              <th key={col}>{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {answer.rows.map((row, idx) => (
                            <tr key={idx}>
                              {answer.columns.map((col) => (
                                <td key={col}>
                                  {row[col] !== null && row[col] !== undefined
                                    ? String(row[col])
                                    : <span className="null-val">null</span>}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

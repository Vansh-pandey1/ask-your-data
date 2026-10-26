import React, { useState, useEffect, useRef } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend
} from 'recharts';
import './App.css';

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || ''
).replace(/\/+$/, '')

// Chart color palette - accessible, distinct colors for grouped series
const CHART_COLORS = ['#2563eb', '#1d4ed8', '#0844c7', '#065f99', '#047857', '#065f46', '#055734', '#04582c', '#044b26', '#034220'];

// Lightweight, crisp SVG icons
function IconDatabase({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}

function IconUpload({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function IconSparkles({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
      <path d="M5 3v4" />
      <path d="M19 17v4" />
      <path d="M3 5h4" />
      <path d="M17 19h4" />
    </svg>
  );
}

function IconCode({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  );
}

function IconTable({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M3 9h18" />
      <path d="M3 15h18" />
      <path d="M9 3v18" />
      <path d="M15 3v18" />
    </svg>
  );
}

function IconCopy({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
    </svg>
  );
}

function IconCheck({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function IconRows({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

function IconColumns({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="6" y1="3" x2="6" y2="21" />
      <line x1="12" y1="3" x2="12" y2="21" />
      <line x1="18" y1="3" x2="18" y2="21" />
    </svg>
  );
}

function IconSearch({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function IconAlertTriangle({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function IconSun({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function IconMoon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function IconMonitor({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

export default function App() {
  const [dataset, setDataset] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [askError, setAskError] = useState(null);

  const [activeTab, setActiveTab] = useState('preview');
  const [showSql, setShowSql] = useState(true);
  const [copiedSql, setCopiedSql] = useState(false);

  // Theme management
  const [theme, setTheme] = useState(() => {
    const stored = localStorage.getItem('askYourData-theme');
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
    return 'system';
  });
  const [themeMenuOpen, setThemeMenuOpen] = useState(false);
  const themeMenuRef = useRef(null);

  // Track system dark mode dynamically
  const [systemIsDark, setSystemIsDark] = useState(() => {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e) => setSystemIsDark(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  // Close theme menu on outside click or escape
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (themeMenuRef.current && !themeMenuRef.current.contains(e.target)) {
        setThemeMenuOpen(false);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setThemeMenuOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  // Persist and apply theme change
  useEffect(() => {
    const html = document.documentElement;
    if (theme === 'system') {
      localStorage.removeItem('askYourData-theme');
      html.setAttribute('data-theme', systemIsDark ? 'dark' : 'light');
    } else {
      localStorage.setItem('askYourData-theme', theme);
      html.setAttribute('data-theme', theme);
    }
  }, [theme, systemIsDark]);

  // Derived active theme for charts and icons: 'light' or 'dark'
  const activeTheme = theme === 'system' ? (systemIsDark ? 'dark' : 'light') : theme;
  const isDark = activeTheme === 'dark';

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
      const res = await fetch(`${API_BASE_URL}/api/ask`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Upload failed');
      }

      setDataset(data);
      setActiveTab('preview');
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
    setAnswer(null);

    try {
      const res = await fetch(`${API_BASE_URL}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim(), row_limit: 100 }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to answer question');
      }

      if (data.error && data.answerable !== false) {
        setAskError(data.error);
        setAnswer(null);
      } else {
        setAnswer(data);
        setAskError(null);
      }
    } catch (err) {
      setAskError(err.message);
      setAnswer(null);
    } finally {
      setAsking(false);
    }
  };

  // Copy SQL to clipboard with feedback
  const handleCopySql = () => {
    if (!answer?.generated_sql) return;
    navigator.clipboard.writeText(answer.generated_sql);
    setCopiedSql(true);
    setTimeout(() => setCopiedSql(false), 2000);
  };

  // Smart chart data transformer: detects chart type and pivots data for Recharts
  const getChartConfig = (result) => {
    if (!result || !result.rows || result.rows.length === 0 || result.columns.length < 2) {
      return null;
    }
    if (result.rows.length > 50) {
      return null;
    }

    const firstRow = result.rows[0];
    const columns = result.columns;

    // Classify columns by type from first row
    const numericCols = columns.filter(col => typeof firstRow[col] === 'number');
    const categoricalCols = columns.filter(col => typeof firstRow[col] === 'string' || typeof firstRow[col] === 'boolean');

    // Heuristic: Identify the "measure" column (what to visualize)
    const measureKeywords = ['count', 'total', 'sum', 'avg', 'average', 'max', 'min', 'mean', 'median', 'value'];
    let measureCol = null;
    for (const kw of measureKeywords) {
      const found = numericCols.find(c => c.toLowerCase().includes(kw));
      if (found) {
        measureCol = found;
        break;
      }
    }
    if (!measureCol && numericCols.length > 1) {
      const cardinality = numericCols.map(col => ({
        col,
        unique: new Set(result.rows.map(r => r[col])).size
      })).sort((a, b) => b.unique - a.unique);
      measureCol = cardinality[0].col;
    }
    if (!measureCol) measureCol = numericCols[0];

    const lowCardinalityThreshold = 10;
    const codedCategoricalCols = numericCols.filter(col => {
      const uniqueVals = new Set(result.rows.map(r => r[col])).size;
      return uniqueVals <= lowCardinalityThreshold && col !== measureCol;
    });

    const allCategoricalCols = [...categoricalCols, ...codedCategoricalCols];

    if (allCategoricalCols.length === 0 || numericCols.length === 0) {
      return null;
    }

    // Case 1: Two+ categorical columns + measure = Grouped Bar Chart
    if (allCategoricalCols.length >= 2 && numericCols.length >= 1) {
      const cat1 = allCategoricalCols[0];
      const cat2 = allCategoricalCols[1];
      const numCol = measureCol;

      const categories = [...new Set(result.rows.map(r => r[cat1]))];
      const seriesValues = [...new Set(result.rows.map(r => r[cat2]))];

      const chartData = categories.map(cat => {
        const row = { [cat1]: cat };
        seriesValues.forEach(sv => {
          const match = result.rows.find(r => r[cat1] === cat && r[cat2] === sv);
          row[String(sv)] = match ? match[numCol] : 0;
        });
        return row;
      });

      return {
        type: 'grouped',
        data: chartData,
        xKey: cat1,
        yKey: numCol,
        seriesKey: cat2,
        seriesValues,
        categories,
        chartTitle: `${numCol} by ${cat1} and ${cat2}`
      };
    }

    // Case 2: One categorical + measure = Simple Bar Chart
    if (allCategoricalCols.length === 1 && numericCols.length >= 1) {
      const catKey = allCategoricalCols[0];
      const numKey = measureCol;

      const uniqueCats = [...new Set(result.rows.map(r => r[catKey]))];
      if (uniqueCats.length > 30) return null;

      return {
        type: 'simple',
        data: result.rows,
        xKey: catKey,
        yKey: numKey,
        chartTitle: `${numKey} by ${catKey}`
      };
    }

    // Case 3: Multiple numeric columns with one categorical = Multi-series Bar Chart
    if (categoricalCols.length === 1 && numericCols.length >= 2) {
      const catKey = categoricalCols[0];
      const uniqueCats = [...new Set(result.rows.map(r => r[catKey]))];
      if (uniqueCats.length > 30) return null;

      return {
        type: 'multi-series',
        data: result.rows,
        xKey: catKey,
        yKeys: numericCols,
        chartTitle: `${numericCols.join(', ')} by ${catKey}`
      };
    }

    return null;
  };

  // Generate dynamic, grounded prompt suggestions from actual dataset schema
  const getSamplePrompts = (ds) => {
    if (!ds || !ds.profile || !ds.profile.columns) return [];
    const cols = ds.profile.columns;
    const numCol = cols.find(c => c.column_type === 'integer' || c.column_type === 'float');
    const catCol = cols.find(c => c.column_type === 'string' && c.unique_count > 1 && c.unique_count <= 25);

    const prompts = [];
    if (catCol && numCol) {
      prompts.push(`What is the average ${numCol.column_name} by ${catCol.column_name}?`);
      prompts.push(`Which ${catCol.column_name} has the highest ${numCol.column_name}?`);
    } else if (numCol) {
      prompts.push(`What is the maximum and average ${numCol.column_name}?`);
    }
    if (cols.length >= 2) {
      prompts.push(`Show top 5 rows sorted by ${cols[0].column_name}`);
    }
    return prompts.slice(0, 3);
  };

  const totalNulls = dataset?.profile?.columns?.reduce(
    (acc, col) => acc + (col.null_count || 0),
    0
  ) ?? 0;

  const totalCells = (dataset?.profile?.total_rows || 0) * (dataset?.profile?.total_columns || 1);
  const nullPercentage = totalCells > 0 ? ((totalNulls / totalCells) * 100).toFixed(1) : 0;

  const chartConfig = getChartConfig(answer);
  const samplePrompts = getSamplePrompts(dataset);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <div className="brand-icon">
            <IconDatabase size={22} />
          </div>
          <div className="brand-titles">
            <h1 className="brand-title">Ask Your Data</h1>
            <span className="brand-tagline">AI-Powered SQL Analytics & Dataset Insights</span>
          </div>
        </div>

        <div className="header-actions">
          {dataset ? (
            <>
              <div className="dataset-pill">
                <span className="pulse-dot"></span>
                <strong>{dataset.file_name}</strong>
                <span className="dataset-pill-meta">
                  &bull; {dataset.total_rows.toLocaleString()} rows
                </span>
              </div>
              <label className="btn btn-secondary">
                <IconUpload size={14} />
                Switch Dataset
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  hidden
                />
              </label>
            </>
          ) : (
            <div className="dataset-pill">
              <span style={{ color: 'var(--text-muted)' }}>&bull; No dataset loaded</span>
            </div>
          )}

          {/* Theme Selector */}
          <div className="theme-selector" ref={themeMenuRef}>
            <button
              type="button"
              className={`theme-toggle ${theme === 'light' ? 'active' : ''}`}
              onClick={() => setThemeMenuOpen(prev => !prev)}
              aria-haspopup="menu"
              aria-expanded={themeMenuOpen}
              aria-label="Change appearance"
              title="Change appearance"
            >
              {theme === 'light' ? <IconSun size={15} /> : theme === 'dark' ? <IconMoon size={15} /> : <IconMonitor size={15} />}
              <span style={{ textTransform: 'capitalize' }}>{theme}</span>
            </button>

            <div className={`theme-dropdown ${themeMenuOpen ? 'open' : ''}`}>
              <button
                type="button"
                className="theme-dropdown-item"
                onClick={() => {
                  setTheme('light');
                  setThemeMenuOpen(false);
                }}
              >
                <IconSun size={14} /> Light
              </button>
              <button
                type="button"
                className="theme-dropdown-item"
                onClick={() => {
                  setTheme('dark');
                  setThemeMenuOpen(false);
                }}
              >
                <IconMoon size={14} /> Dark
              </button>
              <button
                type="button"
                className="theme-dropdown-item"
                onClick={() => {
                  setTheme('system');
                  setThemeMenuOpen(false);
                }}
              >
                <IconMonitor size={14} /> System
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="bento-grid">
        {/* State A: No Dataset Loaded -> Bento Hero Upload */}
        {!dataset && (
          <div className="hero-grid">
            <div className="upload-hero hybrid-card">
              <label className="dropzone">
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  hidden
                />
                <div className="dropzone-icon">
                  <IconUpload size={26} />
                </div>
                <div className="dropzone-title">Upload your CSV dataset</div>
                <div className="dropzone-hint">
                  Drag and drop a file here, or click to browse from your computer
                </div>
                <span className="dropzone-badge">Max 100MB &bull; Comma-separated UTF-8</span>
              </label>

              {uploading && (
                <div className="alert alert-info" style={{ marginTop: 16 }}>
                  <span className="spinner"></span>
                  <div>
                    <strong>Profiling dataset...</strong> Ingesting into isolated SQLite in-memory engine and computing column statistics.
                  </div>
                </div>
              )}

              {uploadError && (
                <div className="alert alert-error" style={{ marginTop: 16 }}>
                  <IconAlertTriangle size={18} />
                  <div>
                    <strong>Upload failed:</strong> {uploadError}
                  </div>
                </div>
              )}
            </div>

            <div className="info-hero hybrid-card">
              <div className="info-hero-content">
                <h3 className="info-hero-title">
                  <IconSparkles size={18} /> How Ask Your Data Works
                </h3>
                <div className="feature-list">
                  <div className="feature-item">
                    <div className="feature-num">1</div>
                    <div className="feature-text">
                      <h4>Deterministic Ingestion</h4>
                      <p>Computes instant schema reflection, types, null rates, and distribution stats without LLM hallucination.</p>
                    </div>
                  </div>
                  <div className="feature-item">
                    <div className="feature-num">2</div>
                    <div className="feature-text">
                      <h4>LangGraph + Gemini Agent</h4>
                      <p>Evaluates answerability, translates natural language to read-only SQL, and validates column names via AST.</p>
                    </div>
                  </div>
                  <div className="feature-item">
                    <div className="feature-num">3</div>
                    <div className="feature-text">
                      <h4>Grounded AI Insights</h4>
                      <p>Inspects executed SQL rows directly to synthesize concise, factually accurate explanations.</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="info-security">
                <IconCode size={16} /> Read-only analytical SQL &bull; In-memory isolation &bull; No mock data
              </div>
            </div>
          </div>
        )}

        {/* State B: Dataset Loaded */}
        {dataset && (
          <>
            {/* 1. Bento Overview KPI Cards */}
            <div className="stat-grid">
              <div className="stat-card stat-card-rows neu-card">
                <div className="stat-icon stat-icon-blue neu-pressed">
                  <IconRows size={22} />
                </div>
                <div className="stat-content">
                  <span className="stat-label">Total Rows</span>
                  <span className="stat-value">
                    {dataset.profile.total_rows.toLocaleString()}
                  </span>
                  <span className="stat-hint">Ingested records</span>
                </div>
              </div>

              <div className="stat-card stat-card-cols neu-card">
                <div className="stat-icon stat-icon-indigo neu-pressed">
                  <IconColumns size={22} />
                </div>
                <div className="stat-content">
                  <span className="stat-label">Total Columns</span>
                  <span className="stat-value">{dataset.profile.total_columns}</span>
                  <span className="stat-hint">Structured schema fields</span>
                </div>
              </div>

              <div className="stat-card stat-card-nulls neu-card">
                <div className="stat-icon stat-icon-amber neu-pressed">
                  <IconTable size={22} />
                </div>
                <div className="stat-content">
                  <span className="stat-label">Missing Values</span>
                  <span className="stat-value">
                    {totalNulls.toLocaleString()}
                  </span>
                  <span className="stat-hint">{nullPercentage}% of total cells</span>
                </div>
              </div>

              <div className="stat-card stat-card-dups neu-card">
                <div className="stat-icon stat-icon-slate neu-pressed">
                  <IconCopy size={22} />
                </div>
                <div className="stat-content">
                  <span className="stat-label">Duplicates</span>
                  <span className="stat-value">{dataset.profile.duplicate_row_count}</span>
                  <span className="stat-hint">Identical record rows</span>
                </div>
              </div>
            </div>

            {/* 2. Bento Dataset Explorer (Preview & Profiles) */}
            <div className="explorer-card neu-card">
              <div className="explorer-header">
                <h2 className="explorer-title">
                  <IconTable size={18} /> Dataset Explorer
                </h2>
                <div className="tabs">
                  <button
                    className={`tab-btn ${activeTab === 'preview' ? 'active' : ''}`}
                    onClick={() => setActiveTab('preview')}
                  >
                    Data Preview <span className="tab-badge">5 rows</span>
                  </button>
                  <button
                    className={`tab-btn ${activeTab === 'summary' ? 'active' : ''}`}
                    onClick={() => setActiveTab('summary')}
                  >
                    Column Profiles <span className="tab-badge">{dataset.profile.total_columns}</span>
                  </button>
                </div>
              </div>

              {activeTab === 'preview' && (
                <div className="table-wrapper">
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
                            <td key={col} className={typeof row[col] === 'number' ? 'numeric-cell' : ''}>
                              {row[col] !== null && row[col] !== undefined ? (
                                String(row[col])
                              ) : (
                                <span className="null-pill">null</span>
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {activeTab === 'summary' && (
                <div className="table-wrapper">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Inferred Type</th>
                        <th>Nulls (%)</th>
                        <th>Unique</th>
                        <th>Computed Distribution / Summary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dataset.profile.columns.map((col) => (
                        <tr key={col.column_name}>
                          <td><strong>{col.column_name}</strong></td>
                          <td><span className="type-pill">{col.column_type}</span></td>
                          <td>{col.null_count} ({col.null_percentage}%)</td>
                          <td>{col.unique_count.toLocaleString()}</td>
                          <td className="stats-detail">
                            {col.numeric_stats && (
                              <span>
                                min: {col.numeric_stats.min} &bull; max: {col.numeric_stats.max} &bull; mean: {col.numeric_stats.mean.toFixed(2)} &bull; median: {col.numeric_stats.median}
                              </span>
                            )}
                            {col.date_range && (
                              <span>
                                span: {col.date_range.min_date} to {col.date_range.max_date}
                              </span>
                            )}
                            {col.categorical_stats && (
                              <span>
                                frequent: {Object.entries(col.categorical_stats).map(([k, v]) => `${k} (${v})`).join(', ')}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* 3. Ask Question Console */}
            <div className="query-card neu-card">
              <div className="query-header">
                <h2 className="query-title">
                  <IconSparkles size={18} /> Ask Your Data in Natural Language
                </h2>
                <span className="query-subtitle">
                  LangGraph Agent &bull; SQLite Engine
                </span>
              </div>

              <form onSubmit={handleAsk} className="query-form">
                <div className="query-input-wrapper">
                  <span className="query-input-icon">
                    <IconSearch size={18} />
                  </span>
                  <input
                    type="text"
                    className="query-input"
                    placeholder="Ask any question about your data (e.g. Which category has the highest average value?)"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    disabled={asking}
                  />
                </div>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={asking || !question.trim()}
                >
                  {asking ? (
                    <>
                      <span className="spinner"></span> Analyzing...
                    </>
                  ) : (
                    <>
                      <IconSparkles size={16} /> Analyze
                    </>
                  )}
                </button>
              </form>

              {/* Dynamic Sample Question Chips */}
              {samplePrompts.length > 0 && (
                <div className="suggestions">
                  <span className="suggestions-label">Suggestions:</span>
                  {samplePrompts.map((p, idx) => (
                    <button
                      key={idx}
                      type="button"
                      className="prompt-chip"
                      onClick={() => setQuestion(p)}
                      disabled={asking}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              )}

              {/* Progress & Error Feedback */}
              {asking && (
                <div className="alert alert-info">
                  <span className="spinner"></span>
                  <div>
                    <strong>Query in progress:</strong> LangGraph is verifying schema columns, generating read-only SQLite syntax, and fetching execution rows...
                  </div>
                </div>
              )}

              {askError && (
                <div className="alert alert-error">
                  <IconAlertTriangle size={18} />
                  <div>
                    <strong>Query error:</strong> {askError}
                  </div>
                </div>
              )}
            </div>

            {/* 4. Results Workspace */}
            {answer && !answer.answerable && (
              <div className="alert alert-warning">
                <IconAlertTriangle size={20} />
                <div>
                  <strong style={{ display: 'block', marginBottom: '4px' }}>Cannot Answer Question with Available Columns</strong>
                  {answer.explanation || answer.error}
                </div>
              </div>
            )}

            {answer && answer.answerable && (
              <div className="results-workspace">
                {/* A. AI Insight */}
                {answer.insight && (
                  <div className="insight-card neu-card">
                    <div className="insight-header">
                      <span className="insight-badge">
                        <IconSparkles size={12} /> AI Insight
                      </span>
                      <span className="insight-title">Grounded Natural-Language Explanation</span>
                    </div>
                    <p className="insight-text">{answer.insight}</p>
                  </div>
                )}

                {/* B. SQL and Statement Type Badge */}
                <div className="sql-box neu-card">
                  <div className="sql-header">
                    <div
                      className="sql-header-left"
                      onClick={() => setShowSql(!showSql)}
                    >
                      <IconCode size={16} />
                      <span>Generated SQL Statement</span>
                      {answer.statement_type && (
                        <span className={`sql-tag ${answer.statement_type === 'SELECT' ? 'sql-tag-select' : 'sql-tag-preview'}`}>
                          {answer.intent === 'SQL_GENERATION' && answer.statement_type !== 'SELECT'
                            ? `${answer.statement_type} — PREVIEW ONLY`
                            : answer.statement_type}
                        </span>
                      )}
                      {answer.correction_attempted && (
                        <span className="sql-tag-retry">Auto-corrected (1 retry)</span>
                      )}
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {showSql ? '▲ collapse' : '▼ expand'}
                      </span>
                    </div>
                    <div className="sql-header-right">
                      <button
                        type="button"
                        className="btn-sql-copy"
                        onClick={handleCopySql}
                      >
                        {copiedSql ? (
                          <>
                            <IconCheck size={12} /> Copied!
                          </>
                        ) : (
                          <>
                            <IconCopy size={12} /> Copy SQL
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                  {showSql && (
                    <pre className="sql-code">
                      <code>{answer.generated_sql}</code>
                    </pre>
                  )}
                </div>

                {/* Warning / Preview Alert for Modifying Statements */}
                {answer.preview?.warning && (
                  <div className={`alert ${answer.preview.is_destructive ? 'alert-error' : 'alert-warning'}`}>
                    <IconAlertTriangle size={18} />
                    <div>
                      <strong>{answer.preview.is_destructive ? 'Destructive Operation Notice' : 'Notice'}:</strong> {answer.preview.warning}
                    </div>
                  </div>
                )}

                {/* C. Optional Chart */}
                {chartConfig && (
                  <div className="chart-card neu-card">
                    <div className="chart-header">
                      <h3 className="chart-title">{chartConfig.chartTitle}</h3>
                      <span className="chart-badge">
                        {chartConfig.type === 'grouped' ? 'Grouped Bar Chart' : chartConfig.type === 'multi-series' ? 'Multi-Series Bar Chart' : 'Bar Chart'}
                      </span>
                    </div>
                    <div style={{ width: '100%', height: 320 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart
                          data={chartConfig.data}
                          margin={{ top: 20, right: 30, left: 20, bottom: 60 }}
                          layout="vertical"
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke={isDark ? '#1e293b' : '#e2e8f0'} />
                          <XAxis
                            type="number"
                            tick={{ fontSize: 12, fill: isDark ? '#94a3b8' : '#64748b' }}
                            tickFormatter={val => val.toLocaleString()}
                            stroke={isDark ? '#1e293b' : '#e2e8f0'}
                          />
                          <YAxis
                            type="category"
                            dataKey={chartConfig.xKey}
                            tick={{ fontSize: 12, fill: isDark ? '#94a3b8' : '#64748b' }}
                            stroke={isDark ? '#1e293b' : '#e2e8f0'}
                            width={120}
                            interval={0}
                          />
                          <Tooltip
                            contentStyle={{
                              borderRadius: '8px',
                              border: `1px solid ${isDark ? '#1e293b' : '#e2e8f0'}`,
                              boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.08)',
                              backgroundColor: isDark ? '#0f172a' : '#ffffff',
                              color: isDark ? '#f8fafc' : '#0f172a'
                            }}
                            formatter={(value, name) => [value.toLocaleString(), name]}
                          />
                          <Legend
                            layout="horizontal"
                            align="center"
                            verticalAlign="top"
                            height={36}
                            iconType="square"
                            iconSize={12}
                            wrapperStyle={{ paddingTop: 8 }}
                          />
                          {chartConfig.type === 'grouped' && chartConfig.seriesValues.map((sv, idx) => (
                            <Bar
                              key={sv}
                              dataKey={String(sv)}
                              fill={CHART_COLORS[idx % CHART_COLORS.length]}
                              radius={[0, 6, 6, 0]}
                              name={String(sv)}
                              minPointSize={4}
                            />
                          ))}
                          {chartConfig.type === 'simple' && (
                            <Bar
                              dataKey={chartConfig.yKey}
                              fill="#2563eb"
                              radius={[0, 6, 6, 0]}
                              name={chartConfig.yKey}
                              minPointSize={4}
                            />
                          )}
                          {chartConfig.type === 'multi-series' && chartConfig.yKeys.map((key, idx) => (
                            <Bar
                              key={key}
                              dataKey={key}
                              fill={CHART_COLORS[idx % CHART_COLORS.length]}
                              radius={[0, 6, 6, 0]}
                              name={key}
                              minPointSize={4}
                            />
                          ))}
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* D. Query Results / Preview Table */}
                <div className="results-card neu-card">
                  <div className="results-header">
                    <h3 className="results-title">
                      <IconTable size={16} /> {answer.statement_type === 'SELECT' ? 'Query Results' : 'Non-Destructive Statement Preview'}
                    </h3>
                    <span className="results-count">
                      {answer.statement_type === 'SELECT'
                        ? `${answer.row_count} ${answer.row_count === 1 ? 'row' : 'rows'} returned`
                        : answer.preview?.preview_type === 'COLUMN_DROP_PREVIEW'
                          ? `Preview only — not executed (Column '${answer.preview?.target_column}' removed)`
                          : `Preview only — not executed (${answer.row_count || 0} rows)`}
                    </span>
                  </div>

                  {answer.preview?.preview_type === 'COLUMN_DROP_PREVIEW' && (
                    <div className="preview-notice">
                      <div className="preview-notice-title">
                        Schema Impact Preview
                      </div>
                      <div>
                        Target Column: <code>{answer.preview?.target_column}</code> (targeted for removal)
                      </div>
                      <div style={{ marginTop: '4px' }}>
                        Remaining Columns ({answer.preview?.remaining_columns?.length || 0}): <code>{answer.preview?.remaining_columns?.join(', ')}</code>
                      </div>
                    </div>
                  )}

                  {answer.rows.length === 0 ? (
                    <div className="empty-results">
                      {answer.preview?.preview_type === 'COLUMN_DROP_PREVIEW'
                        ? `Schema change preview: Column "${answer.preview?.target_column}" would be dropped from the dataset.`
                        : 'No matching records were found in the dataset for this query.'}
                    </div>
                  ) : (
                    <div className="table-wrapper">
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
                                <td
                                  key={col}
                                  className={typeof row[col] === 'number' ? 'numeric-cell' : ''}
                                >
                                  {row[col] !== null && row[col] !== undefined ? (
                                    typeof row[col] === 'number' ? row[col].toLocaleString() : String(row[col])
                                  ) : (
                                    <span className="null-pill">null</span>
                                  )}
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
          </>
        )}
      </main>
    </div>
  );
}
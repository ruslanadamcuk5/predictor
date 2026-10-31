# -*- coding: utf-8 -*-
"""Веб-кабинет истории: устройства, правила, рекомендации и изменения.

Страница полностью статическая (HTML + CSS + JS без сборки), данные берёт
из ``/api/v1/history/*``. Стили и скрипт встроены: сайт alwaysdata отдаёт
один документ, поэтому кабинет открывается быстро и не требует CDN.
"""

from __future__ import annotations

PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Predictor — кабинет истории</title>
<style>
:root{
  --bg:#0b0e14;--bg2:#0f131c;--panel:#141926;--panel2:#1a2030;
  --line:#252c3d;--line2:#2f3850;--text:#e8ecf5;--muted:#8b95ab;
  --dim:#5f6a80;--brand:#5b8cff;--brand2:#7c5cff;--ok:#3ddc97;
  --warn:#f5b545;--bad:#ff5f6d;--info:#5bc9f5;--radius:14px;
  --shadow:0 18px 40px -24px rgba(0,0,0,.9);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.skip{position:absolute;left:12px;top:-60px;z-index:100;background:var(--panel2);
  border:1px solid var(--line2);border-radius:9px;padding:9px 13px;font-weight:650}
.skip:focus{top:12px}
body{
  background:radial-gradient(1200px 600px at 80% -10%,rgba(91,140,255,.16),transparent 60%),
             radial-gradient(900px 500px at 0% 0%,rgba(124,92,255,.12),transparent 55%),
             var(--bg);
  color:var(--text);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  min-height:100vh;-webkit-font-smoothing:antialiased;
}
a{color:var(--brand);text-decoration:none}
button{font:inherit;color:inherit;cursor:pointer}
input,select{font:inherit;color:inherit}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#2b3448;border-radius:8px}
::-webkit-scrollbar-track{background:transparent}
.wrap{max-width:1480px;margin:0 auto;padding:18px 20px 60px}
.hidden{display:none!important}
.muted{color:var(--muted)}
.dim{color:var(--dim)}
.mono{font-variant-numeric:tabular-nums;font-feature-settings:"tnum"}
.small{font-size:12.5px}
.tiny{font-size:11.5px}
.nowrap{white-space:nowrap}
.row{display:flex;align-items:center;gap:10px}
.row.wrap{flex-wrap:wrap}
.spread{display:flex;align-items:center;justify-content:space-between;gap:12px}
.grow{flex:1;min-width:0}
.ellipsis{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* ---------- шапка ---------- */
.top{display:flex;align-items:center;gap:14px;padding:10px 2px 16px;
  position:sticky;top:0;z-index:30;background:rgba(11,14,20,.86);
  -webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);
  border-bottom:1px solid rgba(37,44,61,.0);transition:border-color .2s}
.top.scrolled{border-bottom-color:var(--line)}
.top-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.logo{display:flex;align-items:center;gap:12px;min-width:0}
.logo-mark{width:42px;height:42px;border-radius:13px;flex:none;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  display:grid;place-items:center;font-weight:800;font-size:19px;color:#fff;
  box-shadow:0 10px 26px -12px rgba(91,140,255,.9)}
.logo-text b{display:block;font-size:16.5px;letter-spacing:.4px}
.logo-text span{display:block;color:var(--muted);font-size:12px}
.top-actions{margin-left:auto}
.pill{display:inline-flex;align-items:center;gap:7px;padding:6px 11px;
  border:1px solid var(--line);border-radius:999px;background:var(--panel);
  color:var(--muted);font-size:12px;white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);
  box-shadow:0 0 0 3px rgba(61,220,151,.16)}
.dot.off{background:var(--bad);box-shadow:0 0 0 3px rgba(255,95,109,.16)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;
  border:1px solid var(--line2);background:var(--panel2);border-radius:10px;
  padding:8px 13px;font-size:13px;font-weight:600;transition:.15s;
  white-space:nowrap}
.btn:hover{border-color:#3d4a68;background:#1f2739}
.btn:active{transform:translateY(1px)}
.btn.primary{background:linear-gradient(135deg,var(--brand),var(--brand2));
  border-color:transparent;color:#fff;box-shadow:0 10px 24px -14px rgba(91,140,255,.9)}
.btn.primary:hover{filter:brightness(1.06)}
.btn.ghost{background:transparent}
.btn.sm{padding:5px 9px;font-size:12px;border-radius:8px}
.btn.icon{padding:8px;width:36px;height:36px}

/* ---------- KPI ---------- */
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin-bottom:18px}
.kpi{background:linear-gradient(180deg,var(--panel),var(--bg2));
  border:1px solid var(--line);border-radius:var(--radius);padding:13px 15px;
  box-shadow:var(--shadow);position:relative;overflow:hidden}
.kpi::after{content:"";position:absolute;inset:0 0 auto 0;height:2px;
  background:linear-gradient(90deg,var(--brand),var(--brand2));opacity:.65}
.kpi .k-label{color:var(--muted);font-size:11.5px;text-transform:uppercase;
  letter-spacing:.55px;font-weight:600}
.kpi .k-value{font-size:26px;font-weight:750;letter-spacing:-.4px;margin-top:3px}
.kpi .k-sub{color:var(--dim);font-size:11.5px;margin-top:1px}

/* ---------- карточки устройств ---------- */
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.search{position:relative;flex:1;min-width:200px;max-width:420px}
.search input{width:100%;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;padding:9px 12px 9px 34px;outline:none}
.search input:focus{border-color:#3c5287;box-shadow:0 0 0 3px rgba(91,140,255,.13)}
.search svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);opacity:.55}
.select{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:9px 11px;outline:none}
.check{display:inline-flex;align-items:center;gap:7px;color:var(--muted);
  font-size:12.5px;cursor:pointer;user-select:none}
.check input{accent-color:var(--brand)}

.devices{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:13px}
.device{background:linear-gradient(180deg,var(--panel),#111621);
  border:1px solid var(--line);border-radius:16px;padding:15px 16px;cursor:pointer;
  transition:.16s;position:relative;overflow:hidden;box-shadow:var(--shadow)}
.device:hover{transform:translateY(-2px);border-color:#36425f;background:#161c2b}
.device:focus{outline:none;border-color:var(--brand)}
.device .head{display:flex;align-items:flex-start;gap:10px}
.device .name{font-weight:700;font-size:15px;letter-spacing:-.1px}
.device .meta{color:var(--muted);font-size:11.5px;margin-top:2px}
.device .score{width:52px;height:52px;flex:none;border-radius:50%;
  display:grid;place-items:center;position:relative;font-weight:800;font-size:15px}
.score{position:relative}
.score small{position:absolute;bottom:10px;font-size:8px;font-weight:700;
  color:var(--muted);letter-spacing:.4px;z-index:1}
.score i{position:absolute;inset:0;border-radius:50%;padding:3px;
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 4px),#000 0);
          mask:radial-gradient(farthest-side,transparent calc(100% - 4px),#000 0)}
.score b{position:relative;z-index:1}
.device .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:13px}
.device .cell{background:#0d121c;border:1px solid #1f2636;border-radius:10px;padding:8px 9px}
.device .cell .v{font-size:17px;font-weight:700;letter-spacing:-.3px}
.device .cell .l{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.35px}
.device .spark{margin-top:11px;height:38px}
.device .foot{display:flex;align-items:center;gap:8px;margin-top:11px;flex-wrap:wrap}
.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:999px;
  font-size:11px;font-weight:650;border:1px solid transparent;white-space:nowrap}
.badge.ok{background:rgba(61,220,151,.12);color:var(--ok);border-color:rgba(61,220,151,.25)}
.badge.bad{background:rgba(255,95,109,.12);color:var(--bad);border-color:rgba(255,95,109,.25)}
.badge.warn{background:rgba(245,181,69,.12);color:var(--warn);border-color:rgba(245,181,69,.25)}
.badge.info{background:rgba(91,201,245,.12);color:var(--info);border-color:rgba(91,201,245,.25)}
.badge.brand{background:rgba(91,140,255,.13);color:#9db9ff;border-color:rgba(91,140,255,.28)}
.badge.gray{background:#1b2232;color:var(--muted);border-color:var(--line)}

/* ---------- устройство: шапка и вкладки ---------- */
.dev-head{background:linear-gradient(180deg,var(--panel),#0e131d);
  border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:var(--shadow);
  margin-bottom:14px}
.crumb{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12.5px;margin-bottom:12px}
.dev-title{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.dev-title h1{margin:0;font-size:23px;letter-spacing:-.5px}
.ring{width:72px;height:72px;flex:none;border-radius:50%;display:grid;place-items:center;
  font-weight:800;font-size:20px;position:relative}
.ring i{position:absolute;inset:0;border-radius:50%;padding:4px;
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 5px),#000 0);
          mask:radial-gradient(farthest-side,transparent calc(100% - 5px),#000 0)}
.ring b{position:relative;z-index:1}
.ring small{position:absolute;bottom:12px;font-size:8.5px;font-weight:700;
  color:var(--muted);letter-spacing:.5px;z-index:1}
.dev-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin-top:16px}
.dev-kpis .cell{background:#0c111a;border:1px solid #1e2535;border-radius:11px;padding:9px 11px}
.dev-kpis .v{font-size:18px;font-weight:750;letter-spacing:-.3px}
.dev-kpis .l{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:0 0 16px;overflow:auto}
.tab{padding:9px 14px;border:0;background:none;color:var(--muted);font-weight:650;
  font-size:13px;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tab:hover{color:var(--text)}
.tab.active{color:var(--text);border-bottom-color:var(--brand)}

.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:16px;box-shadow:var(--shadow)}
.panel+.panel{margin-top:12px}
.panel h3{margin:0 0 12px;font-size:14px;letter-spacing:.1px}
.panel .sub{color:var(--muted);font-size:12px;margin:-6px 0 12px}
.cols{display:grid;grid-template-columns:1.5fr 1fr;gap:12px}
.cols3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}

/* ---------- график ---------- */
.chart{height:190px;position:relative}
.chart svg{display:block;width:100%;height:100%;overflow:visible}
.chart .grid-line{stroke:#232b3d;stroke-width:1;stroke-dasharray:3 5}
.chart .axis{fill:var(--dim);font-size:10px}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:11.5px;margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px}

/* ---------- таблицы ---------- */
.table-wrap{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -2px}
.table{width:100%;border-collapse:collapse;font-size:12.8px}
.table th{text-align:left;color:var(--dim);font-weight:600;font-size:10.8px;
  text-transform:uppercase;letter-spacing:.5px;padding:7px 9px;border-bottom:1px solid var(--line)}
.table td{padding:9px;border-bottom:1px solid #1c2331;vertical-align:top}
.table tr:last-child td{border-bottom:0}
.table tbody tr:hover{background:#171e2c}
.bar{height:6px;border-radius:99px;background:#222b3d;overflow:hidden;min-width:60px}
.bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--brand),var(--ok))}
.bar.warn i{background:linear-gradient(90deg,var(--warn),#ff8a5b)}
.bar.bad i{background:linear-gradient(90deg,var(--bad),#ff8a5b)}

/* ---------- правила ---------- */
.cards{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
.rule{background:#10151f;min-width:0;border:1px solid #202839;border-radius:12px;padding:13px 14px}
.rule.disabled{opacity:.62}
.rule .r-head{display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap}
.rule .r-name{font-weight:700;font-size:13.5px}
.rule .r-line{margin-top:7px;color:#c9d2e5;font-size:12.4px}
.rule .r-line b{color:var(--muted);font-weight:600;font-size:11px;
  text-transform:uppercase;letter-spacing:.4px;margin-right:6px}
.rule .metrics{display:flex;gap:16px;flex-wrap:wrap;margin-top:9px;color:var(--muted);font-size:12px}
.rule .metrics b{color:var(--text)}
.split{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.diff{border:1px solid #222a3c;border-radius:9px;padding:8px 10px;background:#0c111a}
.diff .d-label{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px}
.diff .d-before{color:#ff9aa2;text-decoration:line-through;text-decoration-color:rgba(255,95,109,.5);font-size:12px}
.diff .d-after{color:#8ff0c2;font-size:12px}

/* ---------- рекомендации / таймлайн ---------- */
.rec{background:#10151f;border:1px solid #202839;border-radius:12px;padding:14px;
  border-left:3px solid var(--line2)}
.rec.sev-critical{border-left-color:var(--bad)}
.rec.sev-warning{border-left-color:var(--warn)}
.rec.sev-info{border-left-color:var(--brand)}
.rec .r-top{display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap}
.rec .title{font-weight:700;font-size:13.5px}
.rec .why{margin-top:7px;color:#c9d2e5;font-size:12.6px}
.rec .cond{margin-top:6px;padding:7px 9px;border-radius:8px;background:#0b1018;
  border:1px solid #1c2434;color:#a9b6cd;font-size:12px;font-family:ui-monospace,monospace}
.rec .foot{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px;color:var(--muted);font-size:11.5px}
.flow{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:10px}
.flow .step{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:7px;
  background:#141b28;border:1px solid #232c40;font-size:11px;color:var(--muted)}
.flow .step.done{color:var(--ok);border-color:rgba(61,220,151,.3)}
.flow .step.off{color:var(--warn);border-color:rgba(245,181,69,.3)}
.arrow{color:var(--dim);font-size:11px}
.timeline{position:relative;padding-left:20px}
.timeline::before{content:"";position:absolute;left:6px;top:6px;bottom:6px;width:2px;
  background:linear-gradient(180deg,var(--brand),transparent)}
.tl{position:relative;padding:0 0 16px 0}
.tl::before{content:"";position:absolute;left:-19px;top:5px;width:9px;height:9px;
  border-radius:50%;background:var(--brand);box-shadow:0 0 0 3px rgba(91,140,255,.16)}
.tl.created::before{background:var(--ok);box-shadow:0 0 0 3px rgba(61,220,151,.16)}
.tl.deleted::before{background:var(--bad);box-shadow:0 0 0 3px rgba(255,95,109,.16)}
.tl .tl-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tl .tl-time{color:var(--dim);font-size:11px}
.tl .tl-sum{margin-top:3px;color:#c9d2e5;font-size:12.6px}
.tl .tl-changes{margin-top:7px;display:grid;gap:5px}
.tl .chg{font-size:12px;color:var(--muted)}
.tl .chg b{color:var(--text);font-weight:600}
.delta{font-weight:750}
.delta.up{color:var(--ok)}
.delta.down{color:var(--bad)}
.delta.flat{color:var(--muted)}

/* ---------- прогнозы ---------- */
.match{background:#10151f;border:1px solid #202839;border-radius:12px;padding:12px 14px}
.match .m-head{display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap}
.match .teams{font-weight:700;font-size:13.5px}
.match .meta{color:var(--muted);font-size:11.5px;margin-top:1px}
.match .rows{margin-top:9px;display:grid;gap:6px}
.prow{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:6px 8px;
  border-radius:8px;background:#0c111a;border:1px solid #1c2434;font-size:12px}
.prow .lab{font-weight:650;min-width:110px}
.prow .verdict{color:#c9d2e5}
.prow .conf{color:var(--muted);margin-left:auto}
.empty{padding:34px 18px;text-align:center;color:var(--muted);border:1px dashed #26304a;
  border-radius:12px;background:rgba(20,25,38,.4)}
.empty b{display:block;color:var(--text);font-size:14px;margin-bottom:4px}
.loader{padding:28px;text-align:center;color:var(--muted)}
.spinner{width:20px;height:20px;border:2px solid #2a3550;border-top-color:var(--brand);
  border-radius:50%;display:inline-block;animation:spin .7s linear infinite;vertical-align:-4px;margin-right:8px}
@keyframes spin{to{transform:rotate(360deg)}}
.skeleton{background:linear-gradient(90deg,#171e2b,#1d2637,#171e2b);background-size:200% 100%;
  animation:sh 1.2s infinite;border-radius:8px;height:14px}
@keyframes sh{to{background-position:-200% 0}}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.chip{padding:6px 11px;border-radius:999px;border:1px solid var(--line);background:var(--panel);
  color:var(--muted);font-size:12px;font-weight:600}
.chip.active{background:rgba(91,140,255,.14);border-color:rgba(91,140,255,.4);color:#a9c0ff}
.chip .n{opacity:.7;margin-left:3px}
.settings-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}
.setting{background:#0c111a;border:1px solid #1e2535;border-radius:9px;padding:8px 10px;font-size:12px}
.setting .s-k{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px}
.setting .s-v{margin-top:2px;word-break:break-word}
.toast{position:fixed;right:18px;bottom:18px;z-index:50;display:flex;flex-direction:column;gap:8px}
.toast div{background:#1b2434;border:1px solid #33405c;border-radius:10px;padding:10px 14px;
  font-size:12.5px;box-shadow:0 14px 30px -16px #000;animation:tin .2s ease-out}
.toast div.err{border-color:rgba(255,95,109,.5);color:#ffc4c9}
@keyframes tin{from{opacity:0;transform:translateY(6px)}}
.modal{position:fixed;inset:0;background:rgba(5,8,13,.72);display:grid;place-items:center;z-index:60;padding:18px}
.modal .box{background:var(--panel);border:1px solid var(--line2);border-radius:16px;
  padding:20px;max-width:400px;width:100%;box-shadow:0 30px 70px -30px #000}
.modal h3{margin:0 0 6px;font-size:16px}
.modal p{margin:0 0 12px;color:var(--muted);font-size:12.5px}
.modal input{width:100%;background:#0c111a;border:1px solid var(--line2);border-radius:9px;
  padding:10px 12px;outline:none}
.modal .row{margin-top:12px}

/* ---------- управление и фильтры ---------- */
.seg{display:inline-flex;align-items:center;gap:2px;padding:3px;border-radius:10px;
  background:var(--panel);border:1px solid var(--line);flex:none}
.seg button{border:0;background:transparent;color:var(--muted);border-radius:7px;
  padding:5px 9px;font-size:12px;font-weight:650;line-height:1.2}
.seg button:hover{color:var(--text)}
.seg button.active{background:var(--panel2);color:var(--text);
  box-shadow:0 1px 0 rgba(255,255,255,.03) inset}
.toolbar-band{background:rgba(20,25,38,.72);border:1px solid var(--line);
  border-radius:12px;padding:9px;margin-bottom:14px;display:flex;gap:9px;
  align-items:center;flex-wrap:wrap}
.toolbar-band .search{max-width:360px}
.inline-field{display:inline-flex;align-items:center;gap:7px;color:var(--muted);
  font-size:12px;white-space:nowrap}
.inline-field select{padding:7px 9px}
.subhead{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:0 0 10px}
.subhead h3{margin:0}
.count{color:var(--dim);font-size:11.5px}
.attention{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.attention button{text-align:left}
.empty .empty-icon{width:42px;height:42px;margin:0 auto 10px;border-radius:13px;
  display:grid;place-items:center;background:#161d2b;border:1px solid #26304a;
  color:var(--brand);font-size:20px}
.empty .empty-actions{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:13px}
.muted-link{color:var(--muted)}
.muted-link:hover{color:var(--text)}
.chart .hit{fill:rgba(91,140,255,.9)}
.chart .bar-hit{fill:#32456e}
.kpi .k-value.ok{color:var(--ok)}
.kpi .k-value.bad{color:var(--bad)}
.kpi .k-value.warn{color:var(--warn)}
.rule .r-head .mono{font-variant-numeric:tabular-nums}
.copy-id{border:1px dashed #33405c;background:#0c111a;color:var(--muted);
  border-radius:7px;padding:3px 7px;font-size:11px;max-width:100%;
  overflow:hidden;text-overflow:ellipsis}
.copy-id:hover{color:var(--text);border-color:#46577c}
@media (max-width:1180px){
  .kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
  .dev-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
  .cols{grid-template-columns:1fr}
  .cols3{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:820px){
  .wrap{padding:10px 12px 44px}
  .top{flex-wrap:wrap;gap:9px;padding:8px 0 11px}
  .logo-mark{width:36px;height:36px;border-radius:11px;font-size:17px}
  .logo-text b{font-size:15px}
  .logo-text span{display:none}
  .top-actions{width:100%;margin-left:0;gap:6px}
  .top-actions .btn{flex:1;min-width:0;padding:8px 9px;font-size:12px}
  .top-actions .pill{display:none}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
  .kpi{padding:11px 12px}
  .kpi .k-value{font-size:23px}
  .dev-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .device .grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .devices{grid-template-columns:1fr}
  .cols3{grid-template-columns:1fr}
  .split{grid-template-columns:1fr}
  .panel{padding:13px}
  .dev-head{padding:14px}
  .dev-title h1{font-size:20px}
  .dev-title .row{width:100%}
  .dev-title>.row{justify-content:flex-end}
  .ring{width:60px;height:60px;font-size:17px}
  .ring small{bottom:9px;font-size:7.5px}
  .tabs{position:sticky;top:calc(var(--topbar-h, 96px) + 6px);z-index:24;display:grid;
    grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;border:0;
    background:rgba(11,14,20,.94);-webkit-backdrop-filter:blur(12px);
    backdrop-filter:blur(12px);padding:8px 0;margin-bottom:12px;overflow:visible}
  .tab{border:1px solid var(--line);border-radius:9px;background:var(--panel);
    padding:9px 5px;font-size:11.5px;text-align:center;margin:0;line-height:1.25}
  .tab.active{background:rgba(91,140,255,.16);border-color:rgba(91,140,255,.5);
    color:#cfe0ff}
  .toolbar-band{padding:8px;gap:7px}
  .toolbar-band .search{max-width:none;flex:1 1 100%}
  .toolbar-band .select,.toolbar-band .btn{flex:1 1 auto}
  .subhead{gap:7px}
  .chart{height:170px}
  .toast{left:12px;right:12px;bottom:12px}
  .modal{padding:12px}
  .rule .metrics{gap:9px 14px}
  .prow .lab{min-width:0;flex:1 1 100%}
  .prow .conf{margin-left:0}
}
@media (max-width:620px){
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .dev-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .tabs{grid-template-columns:repeat(2,minmax(0,1fr));top:calc(var(--topbar-h, 96px) + 6px)}
  .device .grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .table-wrap{overflow:visible}
  .table thead{display:none}
  .table,.table tbody,.table tr,.table td{display:block;width:100%}
  .table tr{background:#0d121c;border:1px solid #1e2535;border-radius:10px;
    margin-bottom:8px;padding:3px 9px;overflow:hidden}
  .table tr:hover{background:#0d121c}
  .table td{display:flex;justify-content:space-between;align-items:center;gap:12px;
    padding:6px 0;border-bottom:1px solid #182030;text-align:right}
  .table tr td:last-child{border-bottom:0}
  .table td::before{content:attr(data-label);color:var(--dim);font-size:10.5px;
    text-transform:uppercase;letter-spacing:.35px;flex:none;text-align:left}
  .table td:empty{display:none}
  .table td .bar{min-width:92px;flex:1}
  .table td:first-child{font-weight:650}
  .table td:first-child::before{content:""}
  .table td:first-child{justify-content:flex-start;text-align:left}
  .split{grid-template-columns:1fr}
  .toolbar .tiny.dim{width:100%;text-align:right}
}
@media (max-width:400px){
  .kpis,.dev-kpis,.device .grid{grid-template-columns:1fr}
  .tabs{grid-template-columns:1fr 1fr}
  .logo-text b{font-size:14px}
  .kpi .k-value{font-size:21px}
  .dev-title>.row .btn{flex:1}
}
</style>
</head>
<body>
<a class="skip" href="#app">Перейти к содержимому</a>
<div class="wrap">
  <header class="top" id="topBar">
    <div class="logo">
      <div class="logo-mark">P</div>
      <div class="logo-text">
        <b>Predictor</b>
        <span>Кабинет истории правил и рекомендаций</span>
      </div>
    </div>
    <div class="top-actions">
      <span class="pill" id="serverState"><span class="dot" id="serverDot"></span><span id="serverText">Подключение…</span></span>
      <button class="btn ghost" id="btnAuto" type="button" title="Автоматически обновлять данные" aria-pressed="true">
        <span aria-hidden="true">◉</span><span class="btn-label">Авто: вкл</span>
      </button>
      <button class="btn ghost" id="btnRefresh" type="button" title="Обновить данные">
        <span aria-hidden="true">↻</span><span class="btn-label">Обновить</span>
      </button>
      <button class="btn" id="btnDownload" type="button" title="Скачать APK">
        <span aria-hidden="true">↓</span><span class="btn-label">Приложение</span>
      </button>
    </div>
  </header>

  <main id="app">
    <div class="loader"><span class="spinner"></span>Загружаю историю…</div>
  </main>

  <footer class="row wrap tiny dim" style="margin-top:26px;justify-content:center;gap:10px">
    <span>Онлайн-анализ истории и рекомендаций</span>
    <span>·</span>
    <a href="__PREFIX__/api/v1/ping">Проверить связь</a>
    <span>·</span>
    <a href="__PREFIX__/api/v1/update">Обновление приложения</a>
  </footer>

  <div class="toast" id="toast" role="status" aria-live="polite"></div>
  <div class="modal hidden" id="tokenModal">
    <div class="box">
      <h3>Доступ к истории</h3>
      <p>Сервер защищён токеном. Введите его — он сохранится только в этом браузере.</p>
      <input id="tokenInput" type="password" placeholder="Токен доступа" autocomplete="off">
      <div class="row" style="justify-content:flex-end">
        <button class="btn ghost" id="tokenCancel" type="button">Отмена</button>
        <button class="btn primary" id="tokenSave" type="button">Войти</button>
      </div>
    </div>
  </div>
</div>

<script>
"use strict";
const PREFIX = "__PREFIX__";
const API = (PREFIX || "") + "/api/v1";
const TOKEN_KEY = "predictor.history.token";
const S = {
  devices: [], total: null, loadedAt: "", route: {screen: "home"},
  device: null, tab: "overview", cache: {}, loading: false,
  search: "", sort: "quality", onlineOnly: false, quality: "all",
  recFilter: "all", recQuery: "", recSport: "", recSort: "severity",
  eventKind: "all", eventSport: "", eventRule: "", eventLimit: 40,
  eventQuery: "", eventSports: [],
  predStatus: "all", predSport: "", predLimit: 40, predQuery: "",
  predOddsOnly: false, predSports: [], predSort: "recent",
  ruleSport: "", ruleQuery: "", ruleSort: "precision", ruleStatus: "all",
  days: 30, auto: true, lastFetch: 0, settingsQuery: "",
};

function pref(key, fallback){
  try {
    const value = localStorage.getItem("predictor.history." + key);
    return value === null ? fallback : value;
  } catch(e){ return fallback; }
}
function setPref(key, value){
  try { localStorage.setItem("predictor.history." + key, String(value)); } catch(e){}
}
try {
  S.auto = pref("auto", "1") !== "0";
  S.days = Math.max(7, Math.min(180, Number(pref("days", "30")) || 30));
} catch(e){}

function download(name, text, type){
  const blob = new Blob([text], {type: type || "text/plain;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = name;
  document.body.appendChild(link); link.click();
  setTimeout(() => { URL.revokeObjectURL(url); link.remove(); }, 200);
}
function csvCell(value){
  const text = String(value === null || value === undefined ? "" : value);
  return '"' + text.replace(/"/g, '""') + '"';
}
function csv(rows){
  return "\ufeff" + rows.map(row => row.map(csvCell).join(";")).join("\r\n");
}
function emptyHTML(title, text, actions){
  return '<div class="empty"><div class="empty-icon" aria-hidden="true">◌</div>' +
    '<b>'+esc(title)+'</b>'+esc(text || "")+
    (actions ? '<div class="empty-actions">'+actions+'</div>' : '')+'</div>';
}
function tableWrap(head){
  return '<div class="table-wrap"><table class="table"><thead><tr>' +
    head.map(item => '<th>'+esc(item)+'</th>').join("") +
    '</tr></thead><tbody>';
}

function esc(value){
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
function num(value, digits){
  if(value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if(!isFinite(n)) return "—";
  return n.toLocaleString("ru-RU", {maximumFractionDigits: digits === undefined ? 1 : digits});
}
function pct(value){ return value === null || value === undefined ? "—" : num(value, 1) + "%"; }
function signed(value, suffix){
  if(value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if(!isFinite(n)) return "—";
  return (n > 0 ? "+" : "") + num(n, 1) + (suffix || "");
}
function evTone(value){
  if(value === null || value === undefined) return "gray";
  return Number(value) > 0 ? "ok" : (Number(value) < 0 ? "bad" : "gray");
}
function dt(value){
  if(!value) return "—";
  const d = new Date(value);
  if(isNaN(d.getTime())) return String(value);
  return d.toLocaleString("ru-RU", {day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit"});
}
function dshort(value){
  if(!value) return "—";
  const d = new Date(value);
  if(isNaN(d.getTime())) return String(value);
  return d.toLocaleString("ru-RU", {day:"2-digit", month:"2-digit"});
}
function ago(value){
  if(!value) return "нет данных";
  const d = new Date(value);
  if(isNaN(d.getTime())) return String(value);
  const mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  if(mins < 1) return "только что";
  if(mins < 60) return mins + " мин назад";
  const hours = Math.round(mins / 60);
  if(hours < 24) return hours + " ч назад";
  const days = Math.round(hours / 24);
  if(days < 30) return days + " дн назад";
  return d.toLocaleDateString("ru-RU");
}
function token(){
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch(e){ return ""; }
}
function toast(message, isError){
  const box = document.getElementById("toast");
  const item = document.createElement("div");
  if(isError) item.className = "err";
  item.textContent = message;
  box.appendChild(item);
  setTimeout(() => { item.style.opacity = "0"; item.style.transition = "opacity .25s"; }, 3200);
  setTimeout(() => item.remove(), 3600);
}

async function api(path, options){
  const opts = options || {};
  const headers = {"Accept":"application/json"};
  const t = token();
  if(t) headers["Authorization"] = "Bearer " + t;
  if(opts.body) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(API + path, {
      method: opts.method || "GET", headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      cache: "no-store"
    });
  } catch(e){
    throw new Error("Нет связи с сервером");
  }
  if(response.status === 401){
    showTokenModal();
    throw new Error("Требуется токен доступа");
  }
  let data = {};
  try { data = await response.json(); } catch(e){}
  if(!response.ok || data.ok === false){
    throw new Error(data.error || ("Сервер вернул " + response.status));
  }
  return data;
}

function showTokenModal(){
  const modal = document.getElementById("tokenModal");
  if(!modal.classList.contains("hidden")) return;
  modal.classList.remove("hidden");
  document.getElementById("tokenInput").value = token();
  setTimeout(() => document.getElementById("tokenInput").focus(), 30);
}
function hideTokenModal(){ document.getElementById("tokenModal").classList.add("hidden"); }
function copyText(value, label){
  const text = String(value === null || value === undefined ? "" : value);
  const done = () => toast((label || "Скопировано") + ": " + text);
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}
function fallbackCopy(text, done){
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    done();
  } catch(e){ toast("Не удалось скопировать", true); }
}
function sportName(value){
  const found = (S.overview && S.overview.sports || []).find(x => x.sport === value);
  return found ? (found.name || found.short_name || value) : (value || "—");
}
function optionList(items, selected, allLabel){
  return '<option value="">'+esc(allLabel||"Все виды")+'</option>' + items.map(item => {
    const value = typeof item === "string" ? item : item.value;
    const label = typeof item === "string" ? (sportName(item) || item) : item.label;
    return '<option value="'+esc(value)+'"'+(String(selected)===String(value)?" selected":"")+'>'+esc(label)+'</option>';
  }).join("");
}

/* ---------------------------------------------------------------- качество */
function qualityColor(score){
  if(score === null || score === undefined) return "#5f6a80";
  if(score >= 78) return "#3ddc97";
  if(score >= 58) return "#5b8cff";
  if(score >= 38) return "#f5b545";
  return "#ff5f6d";
}
function qualityClass(score){
  if(score >= 78) return "ok";
  if(score >= 58) return "brand";
  if(score >= 38) return "warn";
  return "bad";
}
function ring(score, label, size){
  const color = qualityColor(score);
  const s = size || 52;
  return '<div class="score ring" style="width:'+s+'px;height:'+s+'px;background:conic-gradient(' +
    color + ' ' + Math.max(2, Math.min(100, Number(score)||0)) + '%, #232b3d 0)">' +
    '<i></i><b style="color:'+color+'">' + (score === null || score === undefined ? "—" : Math.round(score)) + '</b>' +
    (label ? '<small>'+esc(label)+'</small>' : '') + '</div>';
}
function deltaHTML(delta, suffix){
  if(delta === null || delta === undefined) return '<span class="delta flat">—</span>';
  const cls = delta >= 3 ? "up" : (delta <= -3 ? "down" : "flat");
  const sign = delta > 0 ? "+" : "";
  return '<span class="delta '+cls+'">'+sign+num(delta,1)+(suffix||"%")+'</span>';
}

/* ---------------------------------------------------------------- график */
function chartSVG(daily){
  const items = (daily || []).slice(-30);
  if(!items.length) return '<div class="empty">Нет данных за период</div>';
  const w = 760, h = 168, padL = 34, padR = 8, padT = 12, padB = 24;
  const iw = w - padL - padR, ih = h - padT - padB;
  const maxTotal = Math.max(4, ...items.map(d => (d.wins||0)+(d.losses||0)+(d.pending||0)));
  const step = iw / items.length;
  const bw = Math.max(3, Math.min(22, step * 0.56));
  let bars = "", line = "", area = "", dots = "";
  let hasLine = false;
  const points = [];
  items.forEach((d, i) => {
    const x = padL + step * i + step / 2;
    const total = (d.wins||0)+(d.losses||0)+(d.pending||0);
    const hh = total ? (total / maxTotal) * ih : 0;
    const y = padT + ih - hh;
    const color = total ? "#2b3a5c" : "#1b2333";
    bars += '<rect x="'+(x-bw/2)+'" y="'+y+'" width="'+bw+'" height="'+Math.max(1,hh)+'" rx="3" fill="'+color+'">' +
      '<title>'+esc(dshort(d.date))+': '+num(d.wins,0)+' зашло · '+num(d.losses,0)+' не зашло' +
      (d.pending ? ' · '+num(d.pending,0)+' ожидает' : '')+'</title></rect>';
    if(d.hit_rate !== null && d.hit_rate !== undefined){
      const py = padT + ih - (Number(d.hit_rate)/100) * ih;
      points.push([x, py]);
      dots += '<circle cx="'+x+'" cy="'+py+'" r="2.6" fill="#5b8cff">' +
        '<title>'+esc(dshort(d.date))+': точность '+num(d.hit_rate,1)+'%</title></circle>';
      hasLine = true;
    }
  });
  if(points.length){
    line = '<polyline fill="none" stroke="#5b8cff" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="' +
      points.map(p => p[0].toFixed(1)+","+p[1].toFixed(1)).join(" ") + '"></polyline>';
    area = '<polygon fill="rgba(91,140,255,.12)" points="' +
      points.map(p => p[0].toFixed(1)+","+p[1].toFixed(1)).join(" ") + " " +
      points[points.length-1][0].toFixed(1)+","+(padT+ih)+" "+points[0][0].toFixed(1)+","+(padT+ih)+'"></polygon>';
  }
  let grid = "";
  [0, 25, 50, 75, 100].forEach(v => {
    const y = padT + ih - (v/100)*ih;
    grid += '<line class="grid-line" x1="'+padL+'" y1="'+y.toFixed(1)+'" x2="'+(w-padR)+'" y2="'+y.toFixed(1)+'"></line>';
    grid += '<text class="axis" x="'+(padL-6)+'" y="'+(y+3.5).toFixed(1)+'" text-anchor="end">'+v+'%</text>';
  });
  const every = Math.max(1, Math.round(items.length / 6));
  let labels = "";
  items.forEach((d, i) => {
    if(i % every && i !== items.length - 1) return;
    const x = padL + step * i + step / 2;
    labels += '<text class="axis" x="'+x.toFixed(1)+'" y="'+(h-6)+'" text-anchor="middle">'+esc(dshort(d.date))+'</text>';
  });
  return '<div class="chart"><svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none">' +
    grid + area + bars + line + dots + labels + '</svg></div>';
}

function sparkline(values){
  const vals = (values || []).filter(v => v !== null && v !== undefined);
  if(vals.length < 2) return '<div class="dim tiny">мало данных</div>';
  const w = 300, h = 36;
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = Math.max(1, max - min);
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - 3 - ((v - min) / span) * (h - 6);
    return x.toFixed(1) + "," + y.toFixed(1);
  });
  const last = vals[vals.length - 1];
  const color = qualityColor(last);
  return '<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" style="width:100%;height:100%">' +
    '<polyline fill="none" stroke="'+color+'" stroke-width="1.8" stroke-linejoin="round" points="'+pts.join(" ")+'"></polyline></svg>';
}

/* ---------------------------------------------------------------- обзор */
function exportDevices(){
  const rows = [["Устройство","Модель","Версия","На связи","Точность, %","ROI, %",
    "EV lower, %","Прибыль","Кэф","Ставок с кэфом","Проверено","Правил","Советов"]];
  S.devices.forEach(d => {
    const st = d.stats || {};
    rows.push([d.name || "", d.model || "", d.app_version || "",
      (d.stale_minutes !== null && d.stale_minutes <= 30) ? "да" : "нет",
      st.hit_rate, st.roi, st.ev_lower, st.profit, st.avg_odds, st.odds_n,
      st.resolved, d.rules.total, d.recs.open]);
  });
  download("predictor-devices.csv", csv(rows), "text/csv;charset=utf-8");
  toast("Экспортировано устройств: " + S.devices.length);
}

function renderHome(){
  const t = S.total || {};
  const weak = S.devices.filter(d => (d.quality.score || 0) < 58).length;
  const profitable = S.devices.filter(d => Number(d.stats.ev_lower) > 0).length;
  const kpis = [
    ["Устройства", num(t.devices,0), (t.online||0)+" на связи · "+weak+" слабых"],
    ["Прогнозы", num(t.predictions,0), "сохранено на сервере"],
    ["Проверено", num(t.resolved,0), (t.wins||0)+" / "+(t.losses||0)+" (победы/поражения)"],
    ["Точность", pct(t.hit_rate), "по всем устройствам"],
    ["ROI", signed(t.roi,"%"), t.odds_n ? ("по "+num(t.odds_n,0)+" ставкам · кэф "+num(t.avg_odds,2)) : "нужны коэффициенты"],
    ["Прибыль", signed(t.profit," ед."), "EV lower "+signed(t.ev,"%")+" · прибыльных "+profitable]
  ];
  const kpiHTML = kpis.map(k => '<div class="kpi"><div class="k-label">'+esc(k[0])+
    '</div><div class="k-value mono'+(k[0]==="Прибыль"&&Number(t.profit)<0?" bad":"")+'">'+
    esc(String(k[1]))+'</div><div class="k-sub">'+esc(k[2])+'</div></div>').join("");

  const q = S.search.trim().toLowerCase();
  let devices = S.devices.filter(d => {
    if(S.onlineOnly && (d.stale_minutes === null || d.stale_minutes > 30)) return false;
    const score = Number(d.quality.score) || 0;
    if(S.quality === "stable" && score < 58) return false;
    if(S.quality === "weak" && score >= 58) return false;
    if(S.quality === "profitable" && !(Number(d.stats.ev_lower) > 0)) return false;
    if(S.quality === "no_odds" && (Number(d.stats.odds_n) || 0) > 0) return false;
    if(!q) return true;
    return [d.name, d.reported_name, d.model, d.platform, d.app_version, d.id]
      .join(" ").toLowerCase().indexOf(q) >= 0;
  });
  const sorters = {
    quality: (a,b) => (b.quality.score||0) - (a.quality.score||0),
    hit: (a,b) => (b.stats.hit_rate||-1) - (a.stats.hit_rate||-1),
    roi: (a,b) => (b.stats.roi ?? -1) - (a.stats.roi ?? -1),
    profit: (a,b) => (b.stats.profit ?? -1) - (a.stats.profit ?? -1),
    ev: (a,b) => (b.stats.ev_lower ?? -1) - (a.stats.ev_lower ?? -1),
    recent: (a,b) => String(b.last_seen||"").localeCompare(String(a.last_seen||"")),
    volume: (a,b) => (b.stats.resolved||0) - (a.stats.resolved||0),
    name: (a,b) => String(a.name||"").localeCompare(String(b.name||""), "ru")
  };
  devices.sort(sorters[S.sort] || sorters.quality);

  let cards = devices.map(d => {
    const st = d.stats || {};
    const online = d.stale_minutes !== null && d.stale_minutes !== undefined && d.stale_minutes <= 30;
    const trend = st.trend;
    const evl = Number(st.ev_lower);
    const tone = !isFinite(evl) ? "gray" : (evl > 0 ? "ok" : (evl < 0 ? "bad" : "gray"));
    return '<article class="device" tabindex="0" role="link" aria-label="Открыть устройство '+esc(d.name)+'" data-device="'+esc(d.id)+'">' +
      '<div class="head"><div class="grow">' +
        '<div class="name ellipsis">'+esc(d.name || "Устройство")+'</div>' +
        '<div class="meta ellipsis">'+esc(d.model || d.platform || "—")+' · v'+esc(d.app_version || "?")+'</div>' +
        '<div class="foot" style="margin-top:7px">' +
          '<span class="badge '+(online?"ok":"gray")+'">'+(online?"● на связи":"○ нет связи")+'</span>' +
          '<span class="badge '+qualityClass(d.quality.score)+'">'+esc(d.quality.label)+'</span>' +
          (trend === null || trend === undefined ? "" : '<span class="badge '+(trend>=3?"ok":(trend<=-3?"bad":"gray"))+'">'+deltaHTML(trend)+' за 7 дн</span>') +
        '</div>' +
      '</div>' + ring(d.quality.score, "QC", 52) + '</div>' +
      '<div class="grid">' +
        '<div class="cell"><div class="v mono">'+pct(st.hit_rate)+'</div><div class="l">точность</div></div>' +
        '<div class="cell"><div class="v mono '+evTone(st.roi)+'">'+signed(st.roi,"%")+'</div><div class="l">ROI</div></div>' +
        '<div class="cell"><div class="v mono">'+signed(st.profit,"")+'</div><div class="l">прибыль, ед.</div></div>' +
        '<div class="cell"><div class="v mono '+tone+'">'+signed(st.ev_lower,"%")+'</div><div class="l">EV lower</div></div>' +
      '</div>' +
      '<div class="spark">'+sparkline(st.spark || [])+'</div>' +
      '<div class="foot">' +
        '<span class="tiny muted">правил: <b>'+num(d.rules.total,0)+'</b></span>' +
        '<span class="tiny muted">·</span>' +
        '<span class="tiny muted">советов: <b>'+num(d.recs.open,0)+'</b></span>' +
        '<span class="tiny muted">·</span>' +
        '<span class="tiny muted">кэф: <b>'+num(st.odds_n,0)+'</b></span>' +
        '<span class="tiny dim" style="margin-left:auto">'+esc(ago(d.last_seen))+'</span>' +
      '</div>' +
    '</article>';
  }).join("");

  if(!cards){
    const hasAny = S.devices.length > 0;
    cards = emptyHTML(hasAny ? "Ничего не найдено" : "Устройств пока нет",
      hasAny ? "Измените поиск или фильтр качества." :
        "Откройте приложение на телефоне, включите онлайн-режим и отправьте историю — устройство появится здесь.",
      (hasAny ? '<button class="btn ghost" type="button" data-reset-filters>Сбросить фильтры</button>' : '') +
      '<button class="btn primary" type="button" data-refresh-home>Обновить</button>');
    cards = '<div style="grid-column:1/-1">'+cards+'</div>';
  }

  const attention = S.devices.filter(d =>
    (d.stale_minutes !== null && d.stale_minutes <= 30) && (d.quality.score || 0) < 58);
  const attentionHTML = attention.length ? '<div class="attention">' +
    attention.slice(0,4).map(d => '<button class="chip" type="button" data-device="'+esc(d.id)+'">'+
      '⚠ '+esc(d.name)+' · '+esc(d.quality.label)+' · '+pct(d.stats.hit_rate)+'</button>').join("") +
    '</div>' : '';

  document.getElementById("app").innerHTML =
    '<section class="kpis">'+kpiHTML+'</section>' +
    attentionHTML +
    '<div class="toolbar-band">' +
      '<div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input id="searchInput" type="search" placeholder="Поиск: название, модель, версия…" value="'+esc(S.search)+'" aria-label="Поиск устройств"></div>' +
      '<select class="select" id="sortSelect" aria-label="Сортировка">' +
        '<option value="quality">Сначала надёжные</option>' +
        '<option value="hit">По точности</option>' +
        '<option value="roi">По ROI</option>' +
        '<option value="profit">По прибыли</option>' +
        '<option value="ev">По EV lower</option>' +
        '<option value="recent">По последней связи</option>' +
        '<option value="volume">По объёму данных</option>' +
        '<option value="name">По названию</option>' +
      '</select>' +
      '<select class="select" id="qualitySelect" aria-label="Фильтр качества">' +
        '<option value="all">Все устройства</option>' +
        '<option value="stable">Надёжные (QC 58+)</option>' +
        '<option value="weak">Слабые (QC &lt; 58)</option>' +
        '<option value="profitable">С плюсовым EV lower</option>' +
        '<option value="no_odds">Без коэффициентов</option>' +
      '</select>' +
      '<label class="check"><input type="checkbox" id="onlineOnly" '+(S.onlineOnly?"checked":"")+'> только на связи</label>' +
      '<span class="grow"></span>' +
      '<span class="tiny dim">'+devices.length+' из '+S.devices.length+' · '+esc(S.loadedAt)+'</span>' +
      '<button class="btn sm ghost" type="button" id="btnExportDevices" title="Экспорт устройств в CSV">Экспорт</button>' +
    '</div>' +
    '<div class="devices">'+cards+'</div>';

  const sortSelect = document.getElementById("sortSelect");
  if(sortSelect) sortSelect.value = S.sort;
  const qualitySelect = document.getElementById("qualitySelect");
  if(qualitySelect) qualitySelect.value = S.quality;
  const searchInput = document.getElementById("searchInput");
  if(searchInput) searchInput.addEventListener("input", e => {
    S.search = e.target.value;
    if(S.timer) clearTimeout(S.timer);
    S.timer = setTimeout(renderHome, 140);
  });
  const onChange = (id, fn) => {
    const el = document.getElementById(id);
    if(el) el.addEventListener("change", fn);
  };
  onChange("sortSelect", e => { S.sort = e.target.value; renderHome(); });
  onChange("qualitySelect", e => { S.quality = e.target.value; renderHome(); });
  onChange("onlineOnly", e => { S.onlineOnly = e.target.checked; renderHome(); });
  const exportBtn = document.getElementById("btnExportDevices");
  if(exportBtn) exportBtn.addEventListener("click", exportDevices);
  const reset = document.querySelector("[data-reset-filters]");
  if(reset) reset.addEventListener("click", () => {
    S.search = ""; S.quality = "all"; S.onlineOnly = false; renderHome();
  });
  const refreshHome = document.querySelector("[data-refresh-home]");
  if(refreshHome) refreshHome.addEventListener("click", refresh);
  document.querySelectorAll("[data-device]").forEach(el => {
    const go = () => { location.hash = "#/device/" + encodeURIComponent(el.dataset.device); };
    el.addEventListener("click", go);
    el.addEventListener("keydown", ev => {
      if(ev.key === "Enter" || ev.key === " "){ ev.preventDefault(); go(); }
    });
  });
}

/* ---------------------------------------------------------------- устройство */
async function loadDevice(id, force){
  const key = id + ":" + S.days;
  if(!force && S.cache[key] && Date.now() - S.cache[key].at < 20000){
    S.device = S.cache[key].device;
    S.overview = S.cache[key].overview;
    S.tab = location.hash.split("/")[3] || S.tab || "overview";
    renderDevice();
    return;
  }
  document.getElementById("app").innerHTML = '<div class="loader"><span class="spinner"></span>Загружаю устройство…</div>';
  try {
    const data = await api("/history/devices/" + encodeURIComponent(id) +
      "/overview?days=" + S.days);
    S.cache[key] = {at: Date.now(), device: data.device, overview: data};
    S.device = data.device;
    S.overview = data;
    S.tab = location.hash.split("/")[3] || "overview";
    if(S.tab === "overview" || S.tab === "rules") S.lastFetch = Date.now();
    renderDevice();
  } catch(e){
    toast(e.message, true);
    document.getElementById("app").innerHTML = '<div class="empty"><b>Не удалось открыть устройство</b>'+esc(e.message)+'</div>';
  }
}

function deviceTabs(){
  const tabs = [
    ["overview","Обзор"],["rules","Правила"],["recommendations","Рекомендации"],
    ["events","История изменений"],["predictions","Прогнозы"],["settings","Настройки"]
  ];
  return '<nav class="tabs" role="tablist" aria-label="Разделы устройства">' + tabs.map(t =>
    '<button class="tab'+(S.tab===t[0]?" active":"")+'" type="button" role="tab" ' +
    'id="tab-'+t[0]+'" aria-controls="tabBody" aria-selected="'+(S.tab===t[0])+'" ' +
    'tabindex="'+(S.tab===t[0]?0:-1)+'" data-tab="'+t[0]+'">'+t[1]+'</button>'
  ).join("") + '</nav>';
}

function renderDevice(){
  const d = S.device;
  if(!d){ location.hash = "#/"; return; }
  const st = d.stats || {};
  const online = d.stale_minutes !== null && d.stale_minutes !== undefined && d.stale_minutes <= 30;
  const head = '<div class="dev-head">' +
    '<div class="crumb"><a href="#/">← Все устройства</a><span>/</span><span>'+esc(d.name)+'</span></div>' +
    '<div class="dev-title">' + ring(d.quality.score, "QC", 72) +
      '<div class="grow">' +
        '<h1>'+esc(d.name || "Устройство")+'</h1>' +
        '<div class="row wrap" style="margin-top:5px">' +
          '<span class="badge '+(online?"ok":"gray")+'">'+(online?"● на связи":"○ нет связи")+'</span>' +
          '<span class="badge '+qualityClass(d.quality.score)+'">'+esc(d.quality.label)+'</span>' +
          '<span class="badge gray">'+esc(d.model || d.platform || "—")+'</span>' +
          '<span class="badge gray">Android · v'+esc(d.app_version || "?")+'</span>' +
          '<span class="tiny dim">последняя связь '+esc(ago(d.last_seen))+'</span>' +
        '</div>' +
      '</div>' +
      '<div class="row wrap dev-actions">' +
        '<button class="btn sm ghost" id="renameBtn" type="button">Переименовать</button>' +
        '<button class="btn sm ghost" id="copyDeviceId" type="button" title="Скопировать ID устройства">ID</button>' +
        '<button class="btn sm ghost" id="exportDevice" type="button" title="Экспортировать данные устройства">Экспорт</button>' +
        '<button class="btn sm" id="deviceRefresh" type="button" title="Обновить устройство">↻</button>' +
      '</div>' +
    '</div>' +
    '<div class="dev-kpis">' +
      '<div class="cell"><div class="v mono">'+pct(st.hit_rate)+'</div><div class="l">точность</div></div>' +
      '<div class="cell"><div class="v mono '+evTone(st.roi)+'">'+signed(st.roi,"%")+'</div><div class="l">ROI · EV '+signed(st.ev,"%")+'</div></div>' +
      '<div class="cell"><div class="v mono">'+signed(st.profit,"")+'</div><div class="l">прибыль, ед.</div></div>' +
      '<div class="cell"><div class="v mono">'+num(st.resolved,0)+'</div><div class="l">проверено</div></div>' +
      '<div class="cell"><div class="v mono">'+num(d.rules.total,0)+'</div><div class="l">правил ('+num(d.rules.enabled,0)+' вкл.)</div></div>' +
      '<div class="cell"><div class="v mono">'+(d.recs.open||0)+'</div><div class="l">открытых советов</div></div>' +
    '</div>' +
    '<div class="row wrap tiny muted" style="margin-top:11px">' +
      (d.quality.reasons || []).map(r => '<span class="badge gray">'+esc(r)+'</span>').join("") +
      '<span style="margin-left:auto">синхронизаций: '+num(d.sync_count,0)+' · первое появление: '+esc(dt(d.first_seen))+'</span>' +
    '</div>' +
  '</div>';

  document.getElementById("app").innerHTML = head + deviceTabs() + '<div id="tabBody"><div class="loader"><span class="spinner"></span>Загружаю…</div></div>';
  document.querySelectorAll("[data-tab]").forEach(el => el.addEventListener("click", () => {
    const next = el.dataset.tab;
    if(next !== "predictions") S.predLimit = 40;
    location.hash = "#/device/" + encodeURIComponent(d.id) + "/" + next;
  }));
  document.getElementById("deviceRefresh").addEventListener("click", () => {
    S.cache = {}; loadDevice(d.id, true);
  });
  document.getElementById("renameBtn").addEventListener("click", renameDevice);
  const copyId = document.getElementById("copyDeviceId");
  if(copyId) copyId.addEventListener("click", () => copyText(d.id, "ID устройства"));
  const exportDevice = document.getElementById("exportDevice");
  if(exportDevice) exportDevice.addEventListener("click", () => exportCurrentTab(d));
  loadTab(false);
}

function exportCurrentTab(d){
  const rows = [["Раздел","Дата","Правило","Вид спорта","Событие","Итог","Метрика 1","Метрика 2"]];
  if(S.tab === "rules" && S._ruleView){
    S._ruleView.forEach(r => rows.push(["Правило", r.last_change_at || "",
      r.name || "", r.sport_name || r.sport || "", r.enabled ? "включено" : "выключено",
      r.conditions_text || "", r.performance && r.performance.hit_rate,
      r.performance && r.performance.roi]));
  } else if(S.tab === "recommendations" && S._recView){
    S._recView.forEach(r => rows.push(["Рекомендация", r.first_seen || "",
      r.rule_name || "", r.sport_name || r.sport || "", r.type_title || r.type || "",
      r.status || "", r.precision_after, r.rec && r.rec.roi_after]));
  } else if(S.tab === "events" && S._eventView){
    S._eventView.forEach(e => rows.push(["Событие", e.at || "",
      e.rule_name || "", e.sport_name || e.sport || "", e.summary || "",
      e.kind || "", e.id, ""]));
  } else if(S.tab === "predictions" && S._predView){
    S._predView.forEach(m => (m.rows || []).forEach(r => rows.push([
      "Прогноз", m.sent_at || "", r.rule_name || "ИИ", m.sport_name || m.sport || "",
      (m.team1 || "") + " — " + (m.team2 || ""), r.label || "",
      r.success === 1 ? "зашло" : (r.success === 0 ? "не зашло" : "ожидает"),
      r.odds === null || r.odds === undefined ? "" : r.odds])));
  }
  const name = "predictor-" + (S.tab || "device") + "-" + String(d.id || "device").slice(0, 12) + ".csv";
  download(name, csv(rows), "text/csv;charset=utf-8");
  toast("Экспортировано строк: " + Math.max(0, rows.length - 1));
}

async function renameDevice(){
  const d = S.device;
  const name = prompt("Название устройства", d.alias || d.name || "");
  if(name === null) return;
  try {
    await api("/history/devices/" + encodeURIComponent(d.id) + "/rename", {
      method: "POST", body: {name: name}
    });
    S.cache = {};
    toast("Название сохранено");
    loadDevice(d.id, true);
  } catch(e){ toast(e.message, true); }
}

async function loadTab(force){
  const d = S.device;
  if(!d) return;
  const body = document.getElementById("tabBody");
  if(!body) return;
  body.onclick = null;
  try {
    if(S.tab === "overview") await renderOverviewTab(body, d);
    else if(S.tab === "rules") await renderRulesTab(body, d);
    else if(S.tab === "recommendations") await renderRecsTab(body, d);
    else if(S.tab === "events") await renderEventsTab(body, d);
    else if(S.tab === "predictions") await renderPredictionsTab(body, d);
    else await renderSettingsTab(body, d);
  } catch(e){
    body.innerHTML = '<div class="empty"><b>Не удалось загрузить раздел</b>'+esc(e.message)+'</div>';
    toast(e.message, true);
  }
}

async function renderOverviewTab(body, d){
  const data = S.overview || await api("/history/devices/" + encodeURIComponent(d.id) + "/overview?days=" + S.days);
  S.overview = data;
  const dev = data.device || d;
  const st = dev.stats || {};
  const daily = (st.daily || []).map(x => ({
    date: x.date, wins: x.wins, losses: x.losses, pending: x.pending, hit_rate: x.hit_rate
  }));
  S._overviewView = {sports: data.sports || [], targets: data.targets || []};
  const sports = (data.sports || []).map(s =>
    '<tr><td data-label="Вид"><div class="row"><span class="badge gray">'+esc(s.short_name || s.sport)+'</span>' +
      '<span>'+esc(s.name)+'</span></div></td>' +
      '<td data-label="Всего" class="mono">'+num(s.total,0)+'</td>' +
      '<td data-label="Победы / поражения" class="mono">'+num(s.wins,0)+' / '+num(s.losses,0)+'</td>' +
      '<td data-label="Точность" class="mono">'+pct(s.hit_rate)+'</td>' +
      '<td data-label="ROI" class="mono '+evTone(s.roi)+'">'+signed(s.roi,"%")+'</td>' +
      '<td data-label="Прибыль" class="mono">'+signed(s.profit,"")+'</td>' +
      '<td data-label="Точность, шкала"><div class="bar '+(s.hit_rate!==null&&s.hit_rate<50?"bad":(s.hit_rate<60?"warn":""))+'">' +
        '<i style="width:'+Math.max(0,Math.min(100,Number(s.hit_rate)||0))+'%"></i></div></td></tr>').join("");
  const targets = (data.targets || []).map(s =>
    '<tr><td data-label="Рынок">'+esc(s.kind || "—")+'</td>' +
    '<td data-label="Всего" class="mono">'+num(s.total,0)+'</td>' +
    '<td data-label="Точность" class="mono">'+pct(s.hit_rate)+'</td>' +
    '<td data-label="ROI" class="mono '+evTone(s.roi)+'">'+signed(s.roi,"%")+'</td>' +
    '<td data-label="Прибыль" class="mono">'+signed(s.profit,"")+'</td></tr>').join("");
  const events = (data.events || []).slice(0, 6).map(e =>
    '<div class="tl '+(e.kind||"")+'"><div class="tl-head"><span class="badge ' +
      (e.kind==="created"?"ok":(e.kind==="deleted"?"bad":"brand"))+'">' +
      (e.kind==="created"?"создано":(e.kind==="deleted"?"удалено":"изменено"))+'</span>' +
      '<b>'+esc(e.rule_name || "Правило")+'</b><span class="tl-time" style="margin-left:auto">'+esc(dt(e.at))+'</span></div>' +
      '<div class="tl-sum">'+esc(e.summary || "")+'</div></div>').join("");
  const reasons = (dev.quality && dev.quality.reasons || []).map(r =>
    '<span class="badge gray">'+esc(r)+'</span>').join("");

  body.innerHTML =
    '<div class="toolbar-band">' +
      '<div class="seg" role="group" aria-label="Период графика">' +
        [7,30,90,180].map(days => '<button type="button" class="'+(S.days===days?"active":"")+'" ' +
          'data-days="'+days+'" aria-pressed="'+(S.days===days)+'">'+days+' дн</button>').join("") +
      '</div>' +
      '<span class="grow"></span>' +
      '<span class="tiny dim">KPI устройства — за всё время · график и события — за '+S.days+' дн</span>' +
      '<button class="btn sm ghost" type="button" id="ovCopyId">Копировать ID</button>' +
      '<button class="btn sm ghost" type="button" id="ovExport">Экспорт CSV</button>' +
    '</div>' +
    (reasons ? '<div class="panel" style="margin-bottom:12px"><div class="subhead"><h3>Качество данных</h3>' +
      '<span class="badge '+qualityClass(dev.quality && dev.quality.score)+'">'+esc(dev.quality && dev.quality.label || "—")+'</span></div>' +
      '<div class="row wrap">'+reasons+'</div></div>' : '') +
    '<div class="panel"><div class="spread"><h3>Точность по дням</h3>' +
      '<span class="tiny muted">столбцы — проверенные прогнозы · линия — % попаданий</span></div>' +
      chartSVG(daily) +
      '<div class="legend"><span><i style="background:#2b3a5c"></i>объём</span>' +
      '<span><i style="background:#5b8cff"></i>точность</span></div>' +
    '</div>' +
    '<div class="cols" style="margin-top:12px">' +
      '<div class="panel"><div class="subhead"><h3>Виды спорта</h3>' +
        '<span class="count">'+num((data.sports||[]).length,0)+'</span></div>' +
        (sports ? '<div class="table-wrap"><table class="table"><thead><tr><th>Вид</th><th>Всего</th><th>W / L</th><th>Точность</th><th>ROI</th><th>Прибыль</th><th></th></tr></thead><tbody>'+sports+'</tbody></table></div>'
                : emptyHTML("Нет проверенных прогнозов", "Статистика появится после первых проверенных матчей.")) +
      '</div>' +
      '<div class="panel"><div class="subhead"><h3>Рынки</h3>' +
        '<span class="count">'+num((data.targets||[]).length,0)+'</span></div>' +
        (targets ? '<div class="table-wrap"><table class="table"><thead><tr><th>Тип</th><th>Всего</th><th>Точность</th><th>ROI</th><th>Прибыль</th></tr></thead><tbody>'+targets+'</tbody></table></div>'
                 : emptyHTML("Нет данных по рынкам", "Проверенные исходы появятся здесь.")) +
      '</div>' +
    '</div>' +
    '<div class="panel" style="margin-top:12px"><div class="spread"><h3>Последние изменения правил</h3>' +
      '<button class="btn sm ghost" type="button" data-goto="events">Вся история →</button></div>' +
      (events ? '<div class="timeline">'+events+'</div>' : emptyHTML("Изменений ещё не было", "История обновится после синхронизации.")) +
    '</div>';

  body.querySelectorAll("[data-days]").forEach(el => el.addEventListener("click", () => {
    const days = Number(el.dataset.days);
    if(!days || days === S.days) return;
    S.days = days; setPref("days", days);
    S.cache = {};
    loadDevice(d.id, true);
  }));
  const copyId = body.querySelector("#ovCopyId");
  if(copyId) copyId.addEventListener("click", () => copyText(d.id, "ID устройства"));
  const exportBtn = body.querySelector("#ovExport");
  if(exportBtn) exportBtn.addEventListener("click", () => {
    const rows = [["Раздел","Название","Всего","Победы","Поражения","Точность, %","ROI, %","Прибыль, ед."]];
    (data.sports || []).forEach(s => rows.push(["Вид спорта", s.name || s.sport,
      s.total, s.wins, s.losses, s.hit_rate, s.roi, s.profit]));
    (data.targets || []).forEach(s => rows.push(["Рынок", s.kind, s.total,
      s.wins, s.losses, s.hit_rate, s.roi, s.profit]));
    download("predictor-device-overview.csv", csv(rows), "text/csv;charset=utf-8");
    toast("Экспортирован обзор устройства");
  });
  const goto = body.querySelector("[data-goto]");
  if(goto) goto.addEventListener("click", () => {
    location.hash = "#/device/" + encodeURIComponent(d.id) + "/events";
  });
}

async function renderRulesTab(body, d){
  const data = await api("/history/devices/" + encodeURIComponent(d.id) + "/rules");
  const items = data.items || [];
  if(!items.length){
    body.innerHTML = emptyHTML("Правил нет",
      "Устройство ещё не прислало конструктор правил. Создайте правило в приложении и включите синхронизацию.",
      '<button class="btn ghost" type="button" data-go-settings>Настройки устройства</button>');
    const go = body.querySelector("[data-go-settings]");
    if(go) go.addEventListener("click", () => { location.hash = "#/device/" + encodeURIComponent(d.id) + "/settings"; });
    return;
  }
  const sports = Array.from(new Set(items.map(r => r.sport).filter(Boolean)));
  if(S.ruleSport && sports.indexOf(S.ruleSport) < 0) S.ruleSport = "";
  body.innerHTML =
    '<div class="toolbar-band">' +
      '<div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input id="ruleSearch" type="search" value="'+esc(S.ruleQuery)+'" placeholder="Поиск по правилу, условию, действию…" aria-label="Поиск правил"></div>' +
      '<select class="select" id="ruleSport" aria-label="Вид спорта">'+optionList(sports, S.ruleSport)+'</select>' +
      '<select class="select" id="ruleStatus" aria-label="Статус правила">' +
        '<option value="all">Все правила</option>' +
        '<option value="enabled">Только включённые</option>' +
        '<option value="disabled">Только выключенные</option>' +
        '<option value="auto">Автоматические</option>' +
        '<option value="positive">С плюсовым EV</option>' +
      '</select>' +
      '<select class="select" id="ruleSort" aria-label="Сортировка правил">' +
        '<option value="precision">По точности</option>' +
        '<option value="roi">По ROI</option>' +
        '<option value="ev">По EV</option>' +
        '<option value="profit">По прибыли</option>' +
        '<option value="resolved">По выборке</option>' +
        '<option value="changes">По изменениям</option>' +
        '<option value="name">По названию</option>' +
      '</select>' +
      '<span class="grow"></span>' +
      '<button class="btn sm ghost" type="button" data-rule-reset>Сбросить</button>' +
      '<button class="btn sm ghost" type="button" data-rule-export>Экспорт</button>' +
    '</div>' +
    '<div class="subhead" id="rulesSummary"></div>' +
    '<div id="rulesList"></div>';

  const paint = () => {
    const q = S.ruleQuery.trim().toLowerCase();
    let list = items.filter(r => {
      if(S.ruleSport && r.sport !== S.ruleSport) return false;
      if(S.ruleStatus === "enabled" && !r.enabled) return false;
      if(S.ruleStatus === "disabled" && r.enabled) return false;
      if(S.ruleStatus === "auto" && !r.auto) return false;
      if(S.ruleStatus === "positive" && !(Number(r.performance && r.performance.ev) > 0)) return false;
      if(!q) return true;
      return [r.name, r.sport_name, r.sport, r.conditions_text, r.action_text,
        r.summary, r.rule_id].join(" ").toLowerCase().indexOf(q) >= 0;
    });
    const value = (r, key) => {
      const p = r.performance || {};
      if(key === "precision") return p.hit_rate === null || p.hit_rate === undefined ? -1 : Number(p.hit_rate);
      if(key === "roi") return p.roi === null || p.roi === undefined ? -1 : Number(p.roi);
      if(key === "ev") return p.ev === null || p.ev === undefined ? -1 : Number(p.ev);
      if(key === "profit") return p.profit === null || p.profit === undefined ? -1 : Number(p.profit);
      if(key === "resolved") return Number(p.resolved) || 0;
      if(key === "changes") return Number(r.change_count) || 0;
      return String(r.name || "");
    };
    list.sort((a, b) => {
      if(S.ruleSort === "name") return value(a,"name").localeCompare(value(b,"name"), "ru");
      return value(b, S.ruleSort) - value(a, S.ruleSort);
    });
    S._ruleView = list;
    const enabled = list.filter(r => r.enabled).length;
    const auto = list.filter(r => r.auto).length;
    const positive = list.filter(r => Number(r.performance && r.performance.ev) > 0).length;
    const summary = document.getElementById("rulesSummary");
    if(summary) summary.innerHTML = '<h3>Правила</h3>' +
      '<span class="count">показано '+num(list.length,0)+' из '+num(items.length,0)+'</span>' +
      '<span class="badge ok">включено '+num(enabled,0)+'</span>' +
      '<span class="badge info">авто '+num(auto,0)+'</span>' +
      '<span class="badge '+(positive?"ok":"gray")+'">EV &gt; 0: '+num(positive,0)+'</span>';

    const bySport = {};
    list.forEach(r => { (bySport[r.sport] = bySport[r.sport] || []).push(r); });
    let html = "";
    Object.keys(bySport).sort().forEach(sport => {
      const group = bySport[sport];
      html += '<div class="panel" style="margin-bottom:12px"><div class="subhead"><h3>'+esc(group[0].sport_name || sport)+
        '</h3><span class="count">'+group.length+'</span></div><div class="cards">';
      group.forEach(r => {
        const p = r.performance || {};
        const sc = r.since_change || {};
        html += '<div class="rule '+(r.enabled?"":"disabled")+'">' +
          '<div class="r-head"><div class="grow"><div class="r-name">'+esc(r.name)+'</div>' +
            '<div class="row wrap" style="margin-top:4px">' +
              '<span class="badge '+(r.enabled?"ok":"gray")+'">'+(r.enabled?"включено":"выключено")+'</span>' +
              (r.auto?'<span class="badge info">авто</span>':'') +
              '<span class="badge gray">приоритет '+num(r.priority,0)+'</span>' +
              '<span class="badge gray">изменений: '+num(r.change_count,0)+'</span>' +
              '<button class="copy-id" type="button" data-copy-rule="'+esc(r.rule_id)+'" title="Скопировать ID правила">'+esc(r.rule_id)+'</button>' +
            '</div></div>' +
            '<div style="text-align:right"><div class="mono" style="font-size:17px;font-weight:750">'+pct(p.hit_rate)+'</div>' +
              '<div class="tiny muted">'+num(p.resolved,0)+' проверено</div></div>' +
          '</div>' +
          '<div class="r-line"><b>Условия</b>'+esc(r.conditions_text || "—")+'</div>' +
          '<div class="r-line"><b>Действие</b>'+esc(r.action_text || "—")+'</div>' +
          '<div class="metrics">' +
            '<span>точность <b>'+pct(p.hit_rate)+'</b></span>' +
            '<span>ROI <b class="'+evTone(p.roi)+'">'+signed(p.roi,"%")+'</b></span>' +
            '<span>EV <b class="'+evTone(p.ev)+'">'+signed(p.ev,"%")+'</b></span>' +
            '<span>прибыль <b>'+signed(p.profit,"")+'</b> ед.</span>' +
            '<span>кэф <b>'+num(p.avg_odds,2)+'</b></span>' +
            '<span>просадка <b>'+num(p.drawdown,1)+'</b></span>' +
            '<span>Wilson <b>'+pct(p.wilson)+'</b></span>' +
            '<span>после правки <b>'+pct(sc.hit_rate)+'</b> / ROI '+signed(sc.roi,"%")+'</span>' +
            '<span>правка: <b>'+esc(dt(r.last_change_at))+'</b></span>' +
          '</div>' +
          '<div class="row" style="margin-top:9px">' +
            (r.last_event ? '<span class="tiny muted ellipsis grow">Последнее: '+esc(r.last_event.summary || r.last_event.kind)+'</span>' : '<span class="grow"></span>') +
            '<button class="btn sm ghost" type="button" data-rule-events="'+esc(r.rule_id)+'" data-rule-sport="'+esc(r.sport)+'">История правила →</button>' +
          '</div>' +
        '</div>';
      });
      html += '</div></div>';
    });
    const listBox = document.getElementById("rulesList");
    if(listBox) listBox.innerHTML = html || emptyHTML("Правила не найдены",
      "Измените поиск, вид спорта или статус.",
      '<button class="btn ghost" type="button" data-rule-reset>Сбросить фильтры</button>');
  };

  const search = document.getElementById("ruleSearch");
  if(search) search.addEventListener("input", e => {
    S.ruleQuery = e.target.value;
    if(S.ruleTimer) clearTimeout(S.ruleTimer);
    S.ruleTimer = setTimeout(paint, 120);
  });
  const bind = (id, event, fn) => {
    const el = document.getElementById(id);
    if(el) el.addEventListener(event, fn);
  };
  bind("ruleSport", "change", e => { S.ruleSport = e.target.value; paint(); });
  bind("ruleStatus", "change", e => { S.ruleStatus = e.target.value; paint(); });
  bind("ruleSort", "change", e => { S.ruleSort = e.target.value; paint(); });
  const sportSelect = document.getElementById("ruleSport");
  if(sportSelect) sportSelect.value = S.ruleSport;
  const statusSelect = document.getElementById("ruleStatus");
  if(statusSelect) statusSelect.value = S.ruleStatus;
  const sortSelect = document.getElementById("ruleSort");
  if(sortSelect) sortSelect.value = S.ruleSort;
  body.querySelectorAll("[data-rule-reset]").forEach(el => el.addEventListener("click", () => {
    S.ruleQuery = ""; S.ruleSport = ""; S.ruleStatus = "all"; S.ruleSort = "precision";
    renderRulesTab(body, d);
  }));
  const exportBtn = body.querySelector("[data-rule-export]");
  if(exportBtn) exportBtn.addEventListener("click", () => exportCurrentTab(d));
  body.onclick = e => {
    const copy = e.target.closest("[data-copy-rule]");
    if(copy) copyText(copy.dataset.copyRule, "ID правила");
    const goto = e.target.closest("[data-rule-events]");
    if(goto){
      S.eventRule = goto.dataset.ruleEvents;
      S.eventSport = goto.dataset.ruleSport || "";
      location.hash = "#/device/" + encodeURIComponent(d.id) + "/events";
    }
  };
  paint();
}

const REC_STATUS = {open:"Открыта", applied:"Применена", resolved:"Закрыта", dismissed:"Скрыта"};
const REC_CLASS = {open:"brand", applied:"ok", resolved:"gray", dismissed:"warn"};
const REC_ACTION = {add_condition:"Добавить условие", add_odds_floor:"Поднять коэффициент",
  remove_condition:"Убрать условие", disable_rule:"Выключить правило",
  adjust_confidence:"Изменить уверенность", enable_rule:"Включить правило"};

async function renderRecsTab(body, d){
  const data = await api("/history/devices/" + encodeURIComponent(d.id) +
    "/recommendations?status=" + encodeURIComponent(S.recFilter) + "&limit=500");
  S.recCounts = data.counts || {};
  const c = S.recCounts;
  const counts = {all: Object.values(c).reduce((a,b)=>a+b,0), open:c.open||0,
    applied:c.applied||0, resolved:c.resolved||0, dismissed:c.dismissed||0};
  const items = data.items || [];
  const sports = Array.from(new Set(items.map(r => r.sport).filter(Boolean)));
  if(S.recSport && sports.indexOf(S.recSport) < 0) S.recSport = "";
  const chips = '<div class="chips">' + [["all","Все"],["open","Открытые"],["applied","Применённые"],["resolved","Закрытые"],["dismissed","Скрытые"]]
    .map(x => '<button class="chip'+(S.recFilter===x[0]?" active":"")+'" type="button" data-rec-filter="'+x[0]+'">'+x[1]+
      '<span class="n">'+(counts[x[0]]||0)+'</span></button>').join("") + '</div>';
  body.innerHTML = chips +
    '<div class="toolbar-band">' +
      '<div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input id="recSearch" type="search" value="'+esc(S.recQuery)+'" placeholder="Поиск по причине, правилу, условию…" aria-label="Поиск рекомендаций"></div>' +
      '<select class="select" id="recSport" aria-label="Вид спорта">'+optionList(sports, S.recSport)+'</select>' +
      '<select class="select" id="recSort" aria-label="Сортировка рекомендаций">' +
        '<option value="severity">По важности</option>' +
        '<option value="precision">По точности после</option>' +
        '<option value="roi">По приросту ROI</option>' +
        '<option value="gain">По приросту точности</option>' +
        '<option value="recent">Сначала новые</option>' +
        '<option value="rule">По правилу</option>' +
      '</select>' +
      '<span class="grow"></span>' +
      '<button class="btn sm ghost" type="button" data-rec-reset>Сбросить</button>' +
      '<button class="btn sm ghost" type="button" data-rec-export>Экспорт</button>' +
    '</div>' +
    '<div class="subhead" id="recsSummary"></div>' +
    '<div id="recsList"></div>';

  const paint = () => {
    const q = S.recQuery.trim().toLowerCase();
    let list = items.filter(r => {
      if(S.recSport && r.sport !== S.recSport) return false;
      if(!q) return true;
      return [r.type_title, r.reason, r.rule_name, r.condition_text, r.sport_name,
        r.status_reason, r.rec_id].join(" ").toLowerCase().indexOf(q) >= 0;
    });
    const sev = {critical:3, warning:2, info:1};
    list.sort((a,b) => {
      if(S.recSort === "recent") return String(b.first_seen || "").localeCompare(String(a.first_seen || ""));
      if(S.recSort === "rule") return String(a.rule_name || "").localeCompare(String(b.rule_name || ""), "ru");
      if(S.recSort === "precision") return (Number(b.precision_after)||0) - (Number(a.precision_after)||0);
      if(S.recSort === "roi") return (Number(b.rec && b.rec.roi_gain)||0) - (Number(a.rec && a.rec.roi_gain)||0);
      if(S.recSort === "gain") return (Number(b.gain)||0) - (Number(a.gain)||0);
      return (sev[b.severity]||0) - (sev[a.severity]||0);
    });
    S._recView = list;
    const summary = document.getElementById("recsSummary");
    if(summary) summary.innerHTML = '<h3>Рекомендации</h3>' +
      '<span class="count">показано '+num(list.length,0)+' из '+num(items.length,0)+'</span>' +
      '<span class="badge brand">открыто '+num(counts.open,0)+'</span>' +
      '<span class="badge ok">применено '+num(counts.applied,0)+'</span>' +
      '<span class="badge gray">закрыто '+num(counts.resolved,0)+'</span>';
    const cards = list.map(r => {
      const rec = r.rec || {};
      const outcome = r.outcome;
      const flow = '<div class="flow">' +
        '<span class="step done">замечена '+esc(dt(r.first_seen))+'</span><span class="arrow">→</span>' +
        (r.applied_at ? '<span class="step done">применена '+esc(dt(r.applied_at))+'</span>'
                      : '<span class="step">не применена</span>') +
        (r.resolved_at ? '<span class="arrow">→</span><span class="step off">закрыта '+esc(dt(r.resolved_at))+'</span>' : '') +
        '</div>';
      let effect = "";
      if(outcome){
        const before = outcome.before || {};
        const after = outcome.after || {};
        effect = '<div class="row wrap" style="margin-top:9px;gap:8px">' +
          '<span class="badge gray">до: '+pct(before.hit_rate)+' · ROI '+signed(before.roi,"%")+' ('+num(before.resolved,0)+')</span>' +
          '<span class="badge gray">после: '+pct(after.hit_rate)+' · ROI '+signed(after.roi,"%")+' ('+num(after.resolved,0)+')</span>' +
          '<span class="badge '+(outcome.verdict==="лучше"?"ok":(outcome.verdict==="хуже"?"bad":"warn"))+'">'+esc(outcome.verdict)+'</span>' +
          '<span class="tiny muted">точность: '+deltaHTML(outcome.delta)+' · ROI: '+signed(outcome.delta_roi,"%")+'</span></div>';
      }
      return '<div class="rec sev-'+(r.severity||"info")+'">' +
        '<div class="r-top"><div class="grow">' +
          '<div class="title">'+esc(r.type_title || REC_ACTION[r.type] || r.type || "Рекомендация")+'</div>' +
          '<div class="row wrap" style="margin-top:4px">' +
            '<span class="badge '+REC_CLASS[r.status]+'">'+esc(REC_STATUS[r.status] || r.status)+'</span>' +
            '<span class="badge gray">'+esc(r.sport_name || r.sport)+'</span>' +
            '<span class="badge gray">'+esc(r.rule_name || "правило")+'</span>' +
            '<button class="copy-id" type="button" data-copy-rec="'+esc(r.rec_id)+'" title="Скопировать ID рекомендации">'+esc(r.rec_id)+'</button>' +
            (r.gain ? '<span class="badge info">точность '+signed(r.gain," п.п.")+'</span>' : '') +
            (rec.roi_gain !== undefined && rec.roi_gain !== null ? '<span class="badge '+(Number(rec.roi_gain)>=0?"ok":"bad")+'">ROI '+signed(rec.roi_gain," п.п.")+'</span>' : '') +
          '</div>' +
        '</div>' +
        '<div style="text-align:right" class="nowrap"><div class="mono" style="font-weight:750">' +
          (rec.roi_before !== undefined && rec.roi_before !== null
            ? signed(rec.roi_before,"%")+' → '+signed(rec.roi_after,"%")
            : pct(r.precision_before)+' → '+pct(r.precision_after)) + '</div>' +
          '<div class="tiny muted">'+(rec.roi_before !== null && rec.roi_before !== undefined ? "ROI правила" : "точность правила")+'</div></div>' +
        '</div>' +
        '<div class="why">'+esc(r.reason || "—")+'</div>' +
        (r.condition_text ? '<div class="cond">'+esc(r.condition_text)+'</div>' : '') +
        effect + flow +
        '<div class="row wrap tiny muted" style="margin-top:8px">' +
          '<span>замечена '+num(r.seen_count,0)+' раз</span>' +
          (r.status_reason ? '<span>· '+esc(r.status_reason)+'</span>' : '') +
          '<span style="margin-left:auto">последняя проверка '+esc(dt(r.last_seen))+'</span>' +
        '</div>' +
      '</div>';
    }).join("");
    const listBox = document.getElementById("recsList");
    if(listBox) listBox.innerHTML = cards ? '<div class="cards">'+cards+'</div>' :
      emptyHTML("Рекомендаций нет", "Сервер пересчитывает их при каждой синхронизации устройства.",
        '<button class="btn ghost" type="button" data-rec-reset>Сбросить фильтры</button>');
  };

  const search = document.getElementById("recSearch");
  if(search) search.addEventListener("input", e => {
    S.recQuery = e.target.value;
    if(S.recTimer) clearTimeout(S.recTimer);
    S.recTimer = setTimeout(paint, 120);
  });
  const sport = document.getElementById("recSport");
  if(sport){ sport.value = S.recSport; sport.addEventListener("change", e => { S.recSport = e.target.value; paint(); }); }
  const sort = document.getElementById("recSort");
  if(sort){ sort.value = S.recSort; sort.addEventListener("change", e => { S.recSort = e.target.value; paint(); }); }
  body.onclick = e => {
    const chip = e.target.closest("[data-rec-filter]");
    if(chip){
      S.recFilter = chip.dataset.recFilter;
      loadTab(true);
      return;
    }
    if(e.target.closest("[data-rec-reset]")){
      S.recQuery = ""; S.recSport = ""; S.recSort = "severity"; S.recFilter = "all";
      loadTab(true);
      return;
    }
    if(e.target.closest("[data-rec-export]")){ exportCurrentTab(d); return; }
    const copy = e.target.closest("[data-copy-rec]");
    if(copy) copyText(copy.dataset.copyRec, "ID рекомендации");
  };
  paint();
}

const EVENT_LABEL = {created:"создано", updated:"изменено", deleted:"удалено"};

async function renderEventsTab(body, d){
  let params = "?limit=" + S.eventLimit;
  if(S.eventKind && S.eventKind !== "all") params += "&kind=" + encodeURIComponent(S.eventKind);
  if(S.eventSport) params += "&sport=" + encodeURIComponent(S.eventSport);
  if(S.eventRule) params += "&rule_id=" + encodeURIComponent(S.eventRule);
  const data = await api("/history/devices/" + encodeURIComponent(d.id) + "/events" + params);
  const items = data.items || [];
  const known = new Set((S.eventSports || []).concat(
    (S.overview && S.overview.sports || []).map(s => s.sport)).concat(items.map(e => e.sport).filter(Boolean)));
  S.eventSports = Array.from(known);
  if(S.eventSport && S.eventSports.indexOf(S.eventSport) < 0) S.eventSport = "";

  body.innerHTML =
    '<div class="chips">' +
      [["all","Все"],["created","Создание"],["updated","Изменения"],["deleted","Удаление"]]
        .map(x => '<button class="chip'+(S.eventKind===x[0]?" active":"")+'" type="button" data-kind="'+x[0]+'">'+x[1]+'</button>').join("") +
      (S.eventRule ? '<button class="chip active" type="button" data-clear-rule="1">правило: '+esc(S.eventRule)+' ✕</button>' : '') +
    '</div>' +
    '<div class="toolbar-band">' +
      '<div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input id="eventSearch" type="search" value="'+esc(S.eventQuery)+'" placeholder="Поиск по правилу, изменению, причине…" aria-label="Поиск событий"></div>' +
      '<select class="select" id="eventSport" aria-label="Вид спорта">'+optionList(S.eventSports, S.eventSport)+'</select>' +
      '<span class="grow"></span>' +
      '<button class="btn sm ghost" type="button" data-event-reset>Сбросить</button>' +
      '<button class="btn sm ghost" type="button" data-event-export>Экспорт</button>' +
    '</div>' +
    '<div class="subhead" id="eventsSummary"></div>' +
    '<div id="eventsList"></div>';

  const paint = () => {
    const q = S.eventQuery.trim().toLowerCase();
    const list = items.filter(e => {
      if(!q) return true;
      const changes = (e.changes || []).map(ch => [ch.label, ch.before, ch.after].join(" ")).join(" ");
      return [e.rule_name, e.summary, e.sport_name, e.kind, changes].join(" ").toLowerCase().indexOf(q) >= 0;
    });
    S._eventView = list;
    const summary = document.getElementById("eventsSummary");
    if(summary) summary.innerHTML = '<h3>История изменений</h3>' +
      '<span class="count">показано '+num(list.length,0)+' из '+num(data.total,0)+'</span>' +
      (S.eventRule ? '<span class="badge brand">фильтр по правилу</span>' : '');
    const rows = list.map(e => {
      const changes = (e.changes || []).map(ch => {
        if(ch.field === "condition_added")
          return '<div class="chg"><b>'+esc(ch.label)+':</b> '+esc(ch.after)+'</div>';
        if(ch.field === "condition_removed")
          return '<div class="chg"><b>'+esc(ch.label)+':</b> '+esc(ch.before)+'</div>';
        return '<div class="chg"><b>'+esc(ch.label)+':</b> ' +
          '<span style="color:#ff9aa2">'+esc(String(ch.before === null ? "—" : ch.before))+'</span> → ' +
          '<span style="color:#8ff0c2">'+esc(String(ch.after === null ? "—" : ch.after))+'</span></div>';
      }).join("");
      const outcome = e.outcome;
      const effect = outcome ? '<div class="row wrap" style="margin-top:7px;gap:7px">' +
        '<span class="badge gray">до '+pct(outcome.before.hit_rate)+' · ROI '+signed(outcome.before.roi,"%")+'</span>' +
        '<span class="badge gray">после '+pct(outcome.after.hit_rate)+' · ROI '+signed(outcome.after.roi,"%")+'</span>' +
        '<span class="badge '+(outcome.verdict==="лучше"?"ok":(outcome.verdict==="хуже"?"bad":"warn"))+'">'+esc(outcome.verdict)+'</span>' +
        '<span class="tiny muted">'+deltaHTML(outcome.delta)+' · ROI '+signed(outcome.delta_roi,"%")+'</span></div>' : "";
      return '<div class="tl '+(e.kind||"")+'">' +
        '<div class="tl-head">' +
          '<span class="badge '+(e.kind==="created"?"ok":(e.kind==="deleted"?"bad":"brand"))+'">'+esc(EVENT_LABEL[e.kind]||e.kind)+'</span>' +
          '<b>'+esc(e.rule_name || "Правило")+'</b>' +
          '<span class="badge gray">'+esc(e.sport_name || e.sport)+'</span>' +
          (e.rec_id ? '<span class="badge info">по рекомендации</span>' : '') +
          '<span class="tl-time" style="margin-left:auto">'+esc(dt(e.at))+'</span>' +
        '</div>' +
        '<div class="tl-sum">'+esc(e.summary || "")+'</div>' +
        (changes ? '<div class="tl-changes">'+changes+'</div>' : '') +
        effect +
        (e.recommendation ? '<div class="tiny muted" style="margin-top:6px">Рекомендация: '+esc(e.recommendation.type_title || "")+' — '+esc(e.recommendation.reason || "")+'</div>' : '') +
      '</div>';
    }).join("");
    const listBox = document.getElementById("eventsList");
    if(listBox) listBox.innerHTML = rows ? '<div class="panel"><div class="timeline">'+rows+'</div></div>' :
      emptyHTML("События не найдены", "Измените фильтры или дождитесь следующей синхронизации.",
        '<button class="btn ghost" type="button" data-event-reset>Сбросить фильтры</button>');
    const moreBox = listBox && listBox.querySelector("[data-more-events]");
    if(moreBox) moreBox.addEventListener("click", () => { S.eventLimit += 40; loadTab(true); });
    if(listBox && items.length < Number(data.total) && list.length){
      listBox.insertAdjacentHTML("beforeend",
        '<div style="text-align:center;margin-top:12px"><button class="btn" type="button" data-more-events>Показать ещё</button></div>');
      const more = listBox.querySelector("[data-more-events]");
      if(more) more.addEventListener("click", () => { S.eventLimit += 40; loadTab(true); });
    }
  };

  const search = document.getElementById("eventSearch");
  if(search) search.addEventListener("input", e => {
    S.eventQuery = e.target.value;
    if(S.eventTimer) clearTimeout(S.eventTimer);
    S.eventTimer = setTimeout(paint, 120);
  });
  const sport = document.getElementById("eventSport");
  if(sport){ sport.value = S.eventSport; sport.addEventListener("change", e => {
    S.eventSport = e.target.value; S.eventLimit = 40; loadTab(true);
  }); }
  body.onclick = e => {
    const kind = e.target.closest("[data-kind]");
    if(kind){ S.eventKind = kind.dataset.kind; S.eventLimit = 40; loadTab(true); return; }
    if(e.target.closest("[data-clear-rule]")){ S.eventRule = ""; S.eventSport = ""; S.eventLimit = 40; loadTab(true); return; }
    if(e.target.closest("[data-event-reset]")){
      S.eventKind = "all"; S.eventSport = ""; S.eventRule = ""; S.eventQuery = ""; S.eventLimit = 40;
      loadTab(true); return;
    }
    if(e.target.closest("[data-event-export]")){ exportCurrentTab(d); return; }
  };
  paint();
}

async function renderPredictionsTab(body, d){
  let params = "?limit=" + S.predLimit + "&status=" + encodeURIComponent(S.predStatus);
  const data = await api("/history/devices/" + encodeURIComponent(d.id) + "/predictions" + params);
  const items = data.items || [];
  const known = new Set((S.predSports || []).concat(
    (S.overview && S.overview.sports || []).map(s => s.sport)).concat(items.map(m => m.sport).filter(Boolean)));
  S.predSports = Array.from(known);
  if(S.predSport && S.predSports.indexOf(S.predSport) < 0) S.predSport = "";

  body.innerHTML =
    '<div class="chips">' +
      [["all","Все"],["win","Победы"],["loss","Поражения"],["pending","Ожидают"]]
        .map(x => '<button class="chip'+(S.predStatus===x[0]?" active":"")+'" type="button" data-pred="'+x[0]+'">'+x[1]+'</button>').join("") +
    '</div>' +
    '<div class="toolbar-band">' +
      '<div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input id="predSearch" type="search" value="'+esc(S.predQuery)+'" placeholder="Поиск: команды, лига, правило…" aria-label="Поиск прогнозов"></div>' +
      '<select class="select" id="predSport" aria-label="Вид спорта">'+optionList(S.predSports, S.predSport)+'</select>' +
      '<select class="select" id="predSort" aria-label="Сортировка прогнозов">' +
        '<option value="recent">Сначала новые</option>' +
        '<option value="roi">По ROI матча</option>' +
        '<option value="odds">По коэффициенту</option>' +
        '<option value="result">Сначала проверенные</option>' +
      '</select>' +
      '<label class="check"><input type="checkbox" id="predOddsOnly" '+(S.predOddsOnly?"checked":"")+'> только с кэфом</label>' +
      '<span class="grow"></span>' +
      '<button class="btn sm ghost" type="button" data-pred-reset>Сбросить</button>' +
      '<button class="btn sm ghost" type="button" data-pred-export>Экспорт</button>' +
    '</div>' +
    '<div class="subhead" id="predsSummary"></div>' +
    '<div id="predsList"></div>';

  const paint = () => {
    const q = S.predQuery.trim().toLowerCase();
    let list = items.filter(m => {
      if(S.predSport && m.sport !== S.predSport) return false;
      if(S.predOddsOnly && !(m.rows || []).some(r => r.odds !== null && r.odds !== undefined)) return false;
      if(!q) return true;
      return [m.team1, m.team2, m.league, m.sport_name, m.sport]
        .concat((m.rows || []).map(r => [r.label, r.verdict, r.rule_name].join(" ")))
        .join(" ").toLowerCase().indexOf(q) >= 0;
    });
    const maxOdds = m => Math.max(0, ...(m.rows || []).map(r => Number(r.odds) || 0));
    const resolved = m => (m.rows || []).reduce((sum, r) => sum + (r.success === null || r.success === undefined ? 0 : 1), 0);
    list.sort((a,b) => {
      if(S.predSort === "roi") return (Number(b.money && b.money.roi)||-999) - (Number(a.money && a.money.roi)||-999);
      if(S.predSort === "odds") return maxOdds(b) - maxOdds(a);
      if(S.predSort === "result") return resolved(b) - resolved(a);
      return String(b.sent_at || "").localeCompare(String(a.sent_at || ""));
    });
    S._predView = list;
    const summary = document.getElementById("predsSummary");
    if(summary) summary.innerHTML = '<h3>Прогнозы</h3>' +
      '<span class="count">показано '+num(list.length,0)+' из '+num(data.total,0)+' матчей</span>' +
      '<span class="badge gray">строк: '+num(list.reduce((n,m) => n + (m.rows||[]).length, 0),0)+'</span>';
    const cards = list.map(m => {
      const rows = (m.rows || []).map(r => {
        const cls = r.success === 1 ? "ok" : (r.success === 0 ? "bad" : "gray");
        const result = r.success === 1 ? "зашло" : (r.success === 0 ? "не зашло" : "ожидает");
        return '<div class="prow">' +
          '<span class="lab">'+esc(r.label || r.target)+'</span>' +
          '<span class="verdict">'+esc(r.verdict || "—")+'</span>' +
          (r.rule_name ? '<span class="badge gray">'+esc(r.rule_name)+'</span>' : '<span class="badge info">ИИ</span>') +
          '<span class="conf mono">'+(r.confidence===null||r.confidence===undefined?"":"уверенность "+num(r.confidence*100,0)+"%")+'</span>' +
          (r.odds!==null&&r.odds!==undefined?'<span class="badge gray mono">кэф '+num(r.odds,2)+'</span>':'') +
          '<span class="badge '+cls+'">'+result+(r.score?(" · "+esc(r.score)):"")+(r.total!==null&&r.total!==undefined?(" · "+num(r.total,1)):"")+'</span>' +
        '</div>';
      }).join("");
      return '<div class="match"><div class="m-head"><div class="grow">' +
        '<div class="teams">'+esc(m.team1)+' — '+esc(m.team2)+'</div>' +
        '<div class="meta">'+esc(m.league || "—")+' · '+esc(m.sport_name || m.sport)+' · '+esc(dt(m.sent_at))+'</div>' +
        '</div>'+(m.money && m.money.odds_n ? '<div style="text-align:right"><div class="mono '+evTone(m.money.roi)+'" style="font-weight:750">'+signed(m.money.roi,"%")+'</div><div class="tiny muted">ROI · '+signed(m.money.profit,"")+' ед. · кэф '+num(m.money.avg_odds,2)+'</div></div>' : '')+'</div>' +
        '<div class="rows">'+(rows || '<div class="tiny muted">Без прогнозов</div>')+'</div></div>';
    }).join("");
    const listBox = document.getElementById("predsList");
    if(listBox) listBox.innerHTML = cards ? '<div class="cards">'+cards+'</div>' :
      emptyHTML("Прогнозов нет", "Устройство ещё не присылало историю или фильтры слишком строгие.",
        '<button class="btn ghost" type="button" data-pred-reset>Сбросить фильтры</button>');
    if(listBox && items.length < Number(data.total) && list.length){
      listBox.insertAdjacentHTML("beforeend",
        '<div style="text-align:center;margin-top:12px"><button class="btn" type="button" data-more-pred>Показать ещё</button></div>');
      const more = listBox.querySelector("[data-more-pred]");
      if(more) more.addEventListener("click", () => { S.predLimit += 40; loadTab(true); });
    }
  };

  const search = document.getElementById("predSearch");
  if(search) search.addEventListener("input", e => {
    S.predQuery = e.target.value;
    if(S.predTimer) clearTimeout(S.predTimer);
    S.predTimer = setTimeout(paint, 120);
  });
  const sport = document.getElementById("predSport");
  if(sport){ sport.value = S.predSport; sport.addEventListener("change", e => { S.predSport = e.target.value; paint(); }); }
  const sort = document.getElementById("predSort");
  if(sort){ sort.value = S.predSort; sort.addEventListener("change", e => { S.predSort = e.target.value; paint(); }); }
  const oddsOnly = document.getElementById("predOddsOnly");
  if(oddsOnly) oddsOnly.addEventListener("change", e => { S.predOddsOnly = e.target.checked; paint(); });
  body.onclick = e => {
    const chip = e.target.closest("[data-pred]");
    if(chip){ S.predStatus = chip.dataset.pred; S.predLimit = 40; loadTab(true); return; }
    if(e.target.closest("[data-pred-reset]")){
      S.predStatus = "all"; S.predSport = ""; S.predQuery = ""; S.predOddsOnly = false;
      S.predSort = "recent"; S.predLimit = 40; loadTab(true); return;
    }
    if(e.target.closest("[data-pred-export]")){ exportCurrentTab(d); return; }
  };
  paint();
}

async function renderSettingsTab(body, d){
  const meta = d.meta || {};
  const settings = meta.settings || {};
  const flat = [];
  const walk = (obj, prefix) => {
    Object.keys(obj || {}).forEach(k => {
      const v = obj[k];
      if(v && typeof v === "object" && !Array.isArray(v)) walk(v, prefix ? prefix + "." + k : k);
      else flat.push([prefix ? prefix + "." + k : k, Array.isArray(v) ? v.join(", ") : String(v)]);
    });
  };
  walk(settings, "");
  const auto = settings.auto_rules || {};
  const template = (settings.algorithm_mode || "—");
  const online = settings.online || {};
  body.innerHTML =
    '<div class="toolbar-band">' +
      '<div class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input id="settingsSearch" type="search" value="'+esc(S.settingsQuery)+'" placeholder="Поиск по названию настройки…" aria-label="Поиск настроек"></div>' +
      '<span class="grow"></span>' +
      '<button class="btn sm ghost" type="button" data-settings-copy>Копировать ID</button>' +
      '<button class="btn sm ghost" type="button" data-settings-export>Экспорт JSON</button>' +
    '</div>' +
    '<div class="cols">' +
      '<div class="panel"><h3>Устройство</h3>' +
        '<div class="settings-grid">' +
          '<div class="setting"><div class="s-k">Название</div><div class="s-v">'+esc(d.reported_name || d.name)+'</div></div>' +
          '<div class="setting"><div class="s-k">Модель</div><div class="s-v">'+esc(d.model || "—")+'</div></div>' +
          '<div class="setting"><div class="s-k">Платформа</div><div class="s-v">'+esc(d.platform || "—")+'</div></div>' +
          '<div class="setting"><div class="s-k">Версия приложения</div><div class="s-v">'+esc(d.app_version || "—")+'</div></div>' +
          '<div class="setting"><div class="s-k">Идентификатор</div><div class="s-v mono">'+esc(d.id)+'</div></div>' +
          '<div class="setting"><div class="s-k">Первое появление</div><div class="s-v">'+esc(dt(d.first_seen))+'</div></div>' +
          '<div class="setting"><div class="s-k">Последняя связь</div><div class="s-v">'+esc(dt(d.last_seen))+'</div></div>' +
          '<div class="setting"><div class="s-k">Синхронизаций</div><div class="s-v">'+num(d.sync_count,0)+'</div></div>' +
          '<div class="setting"><div class="s-k">Онлайн</div><div class="s-v">'+(online.enabled?"включён":"выключен")+' · '+esc(online.base_url||"—")+'</div></div>' +
        '</div>' +
      '</div>' +
      '<div class="panel"><h3>Авто-правила</h3>' +
        '<div class="settings-grid">' +
          '<div class="setting"><div class="s-k">Включены</div><div class="s-v">'+(auto.enabled?"да":"нет")+'</div></div>' +
          '<div class="setting"><div class="s-k">Мин. точность</div><div class="s-v">'+esc(String(auto.min_precision||"—"))+'%</div></div>' +
          '<div class="setting"><div class="s-k">Мин. выборка</div><div class="s-v">'+esc(String(auto.min_samples||"—"))+'</div></div>' +
          '<div class="setting"><div class="s-k">Макс. правил</div><div class="s-v">'+esc(String(auto.max_rules||"—"))+'</div></div>' +
          '<div class="setting"><div class="s-k">Активный вид</div><div class="s-v">'+esc(settings.active_sport || "—")+'</div></div>' +
          '<div class="setting"><div class="s-k">Режим</div><div class="s-v">'+esc(template)+'</div></div>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="panel" style="margin-top:12px"><div class="subhead"><h3>Все присланные настройки</h3>' +
      '<span class="count" id="settingsCount"></span></div>' +
      '<div class="sub">Без токенов и ключей: приложение отправляет только параметры анализа.</div>' +
      '<div class="settings-grid" id="settingsList"></div>' +
    '</div>';

  const paint = () => {
    const q = S.settingsQuery.trim().toLowerCase();
    const list = flat.filter(x => !q || x[0].toLowerCase().indexOf(q) >= 0 || String(x[1]).toLowerCase().indexOf(q) >= 0);
    const box = document.getElementById("settingsList");
    if(box) box.innerHTML = list.length ? list.map(x =>
      '<div class="setting"><div class="s-k">'+esc(x[0])+'</div><div class="s-v">'+esc(x[1])+'</div></div>'
    ).join("") : emptyHTML("Настройки не найдены", "Измените поисковый запрос.",
      '<button class="btn ghost" type="button" data-settings-reset>Сбросить</button>');
    const count = document.getElementById("settingsCount");
    if(count) count.textContent = "показано " + list.length + " из " + flat.length;
  };

  const search = document.getElementById("settingsSearch");
  if(search) search.addEventListener("input", e => {
    S.settingsQuery = e.target.value;
    if(S.settingsTimer) clearTimeout(S.settingsTimer);
    S.settingsTimer = setTimeout(paint, 100);
  });
  body.onclick = e => {
    if(e.target.closest("[data-settings-copy]")){ copyText(d.id, "ID устройства"); return; }
    if(e.target.closest("[data-settings-reset]")){ S.settingsQuery = ""; renderSettingsTab(body, d); return; }
    if(e.target.closest("[data-settings-export]")){
      const object = {};
      flat.forEach(x => { object[x[0]] = x[1]; });
      download("predictor-settings-" + String(d.id).slice(0,12) + ".json",
        JSON.stringify({device: {id: d.id, name: d.name, model: d.model,
          app_version: d.app_version, last_seen: d.last_seen}, settings: object}, null, 2),
        "application/json;charset=utf-8");
      toast("Настройки экспортированы");
    }
  };
  paint();
}

function syncTopbarHeight(){
  const top = document.getElementById("topBar");
  if(top) document.documentElement.style.setProperty("--topbar-h",
    Math.round(top.getBoundingClientRect().height) + "px");
}
window.addEventListener("resize", syncTopbarHeight);

/* ---------------------------------------------------------------- маршруты */
async function loadDevices(){
  const data = await api("/history/devices");
  S.devices = data.devices || [];
  S.total = data.total || {};
  S.loadedAt = dt(data.server_time);
  S.lastFetch = Date.now();
  document.getElementById("serverText").textContent = "Сервер " + (data.server_version || "");
  document.getElementById("serverDot").classList.remove("off");
}

async function route(){
  const hash = location.hash || "#/";
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  try {
    if(parts[0] === "device" && parts[1]){
      if(!S.devices.length) await loadDevices();
      if(!S.device || S.device.id !== decodeURIComponent(parts[1])){
        S.tab = parts[2] || "overview";
        S.overview = null;
        await loadDevice(decodeURIComponent(parts[1]), true);
      } else {
        const nextTab = parts[2] || "overview";
        if(nextTab !== S.tab){ S.tab = nextTab; renderDevice(); }
      }
    } else {
      S.device = null;
      await loadDevices();
      document.getElementById("app").innerHTML = "";
      renderHome();
    }
  } catch(e){
    document.getElementById("app").innerHTML = '<div class="empty"><b>Ошибка загрузки</b>'+esc(e.message)+'</div>';
    toast(e.message, true);
  }
}

async function refresh(quiet){
  if(S.refreshing) return;
  S.refreshing = true;
  const btn = document.getElementById("btnRefresh");
  const y = window.scrollY;
  if(btn) btn.disabled = true;
  try {
    S.cache = {};
    if(location.hash.indexOf("#/device/") === 0 && S.device){
      const id = S.device.id;
      await loadDevices();
      await loadDevice(id, true);
    } else {
      await loadDevices();
      renderHome();
    }
    S.lastFetch = Date.now();
    if(!quiet) toast("Данные обновлены");
  } catch(e){ if(!quiet) toast(e.message, true); }
  finally {
    S.refreshing = false;
    if(btn) btn.disabled = false;
    window.scrollTo(0, y);
  }
}

function updateAutoButton(){
  const btn = document.getElementById("btnAuto");
  if(!btn) return;
  btn.setAttribute("aria-pressed", String(S.auto));
  const label = btn.querySelector(".btn-label");
  if(label) label.textContent = "Авто: " + (S.auto ? "вкл" : "выкл");
  btn.classList.toggle("ghost", !S.auto);
}

document.getElementById("btnRefresh").addEventListener("click", () => refresh(false));
document.getElementById("btnAuto").addEventListener("click", () => {
  S.auto = !S.auto;
  setPref("auto", S.auto ? "1" : "0");
  updateAutoButton();
  toast(S.auto ? "Автообновление включено" : "Автообновление выключено");
});
document.getElementById("btnDownload").addEventListener("click", () => {
  window.location.href = (PREFIX || "") + "/api/v1/update";
});
document.getElementById("tokenSave").addEventListener("click", () => {
  const value = document.getElementById("tokenInput").value.trim();
  try { localStorage.setItem(TOKEN_KEY, value); } catch(e){}
  hideTokenModal();
  route();
});
document.getElementById("tokenInput").addEventListener("keydown", e => {
  if(e.key === "Enter") document.getElementById("tokenSave").click();
});
document.getElementById("tokenCancel").addEventListener("click", hideTokenModal);
document.getElementById("tokenModal").addEventListener("click", e => {
  if(e.target.id === "tokenModal") hideTokenModal();
});
document.addEventListener("keydown", e => {
  if(e.key === "Escape") hideTokenModal();
});
window.addEventListener("hashchange", route);
window.addEventListener("scroll", () => {
  const top = document.getElementById("topBar");
  if(top) top.classList.toggle("scrolled", window.scrollY > 4);
}, {passive:true});
document.addEventListener("visibilitychange", () => {
  if(document.hidden) return;
  if(S.auto && Date.now() - S.lastFetch > 60000) refresh(true);
});
setInterval(() => {
  if(document.hidden || !S.auto || S.refreshing) return;
  if(Date.now() - S.lastFetch < 90000) return;
  refresh(true);
}, 60000);

updateAutoButton();
syncTopbarHeight();
setTimeout(syncTopbarHeight, 80);
route().catch(e => {
  document.getElementById("app").innerHTML = '<div class="empty"><b>Сервер недоступен</b>'+esc(e.message)+'</div>';
  document.getElementById("serverDot").classList.add("off");
  document.getElementById("serverText").textContent = "Нет связи";
});
</script>
</body>
</html>
"""


def render(prefix=""):
    return PAGE.replace("__PREFIX__", prefix or "")

const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = text => text.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
const terminal = ['complete', 'failed', 'cancelled', 'interrupted'];
let token, selected, current, checkedRequest, timer, polling = false, history = [], activeRun = null;
function error(message) { $('error').textContent = message; $('error').classList.toggle('hidden', !message); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Launch-Token':token}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function request() { return {repo:$('repo').value.trim(),base:$('base').value.trim(),candidate:$('candidate').value.trim(),profile:$('profile').checked,demo:$('demo-months').checked}; }
function commitCards(revisions) {
  return Object.entries(revisions).map(([side, value])=>`<div class="commit"><small>${escape(side.toUpperCase())}</small><strong title="${escape(value.sha)}">${escape(value.sha.slice(0,12))}</strong><p title="${escape(value.summary)}">${escape(value.summary)}</p></div>`).join('');
}
function invalidate() { checkedRequest=null; $('start').disabled=true; $('preflight').classList.add('hidden'); }
$('form').addEventListener('input', invalidate);
$('form').addEventListener('submit', async event => {
  event.preventDefault(); error(''); $('check').disabled=true; $('check').textContent='Checking…';
  const submitted = request();
  try {
    const data=await api('/api/preflight',submitted);
    if (JSON.stringify(submitted)!==JSON.stringify(request())) return;
    $('preflight').classList.remove('hidden');
    $('preflight').innerHTML = (data.revisions ? `<div class="commits">${commitCards(data.revisions)}</div>` : '') + `<ul class="check-list">${data.checks.map(x=>`<li>${escape(x)}</li>`).join('')}</ul>`;
    if (!data.ok) error(data.errors.join('\n'));
    else { checkedRequest={...submitted,base:data.revisions.baseline.sha,candidate:data.revisions.candidate.sha}; $('start').disabled=!!activeRun; }
  } catch (e) { error(e.message); }
  finally { $('check').disabled=false; $('check').innerHTML='Check revisions <span>↗</span>'; }
});
$('start').onclick=async()=>{
  if (!checkedRequest) return;
  $('start').disabled=true; error('');
  try { const state=await api('/api/runs',checkedRequest); activeRun=state.id; await openRun(state.id); }
  catch(e){error(e.message);$('start').disabled=false;}
};
$('cancel').onclick=async()=>{ if(!selected)return; try{await api(`/api/runs/${selected}/cancel`,{});$('cancel').disabled=true;}catch(e){error(e.message);} };
$('new-run').onclick=()=>{
  stopAnalysis(); resetCommitRange(); selected=null;current=null; clearTimeout(timer);error('');$('setup').classList.remove('hidden');$('run').classList.add('hidden');$('empty').classList.remove('hidden');invalidate();refreshHistory();scheduleRange();
};
$('refresh').onclick=()=>refreshHistory().catch(e=>error(e.message));
async function refreshHistory(){
  history=await api('/api/runs'); activeRun=history.find(x=>!terminal.includes(x.status))?.id || null;
  $('history').innerHTML=history.length?history.map(run=>`<button data-id="${escape(run.id)}" class="${selected===run.id?'selected':''}"><strong>${escape(run.revisions?.baseline?.sha?.slice(0,7)||'—')} → ${escape(run.revisions?.candidate?.sha?.slice(0,7)||'—')}</strong><small>${escape(pretty(run.status))} · ${new Date(run.started*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</small></button>`).join(''):'<p class="empty-history">No investigations yet.<br>Your real runs will appear here.</p>';
  $('history').querySelectorAll('button').forEach(button=>button.onclick=()=>openRun(button.dataset.id));
}
async function openRun(id){
  stopAnalysis(); resetCommitRange(); selected=id; clearTimeout(timer);error('');$('setup').classList.add('hidden');$('empty').classList.add('hidden');$('run').classList.remove('hidden');$('results').classList.add('hidden');$('detail').classList.add('hidden');
  await refreshHistory(); await poll();
}
async function poll(){
  if(!selected || polling) { if(selected)timer=setTimeout(poll,1000); return; }
  polling=true;const id=selected;
  try {
    const state=await api(`/api/runs/${id}`); if(id!==selected)return;
    current=state;renderRun(state);
    if(!rangeRequest)showCommitRange({repo:state.repo,base:state.revisions.baseline.sha,candidate:state.revisions.candidate.sha});
    if($('log-details').open || state.status==='failed') {const data=await api(`/api/runs/${id}/log`); if(id===selected)$('logs').textContent=data.text;}
    if(terminal.includes(state.status)){ await refreshHistory(); }
    else timer=setTimeout(poll,1000);
  } catch(e){error(e.message);timer=setTimeout(poll,2000);}
  finally{polling=false;}
}
$('log-details').addEventListener('toggle',async()=>{if($('log-details').open&&selected){try{$('logs').textContent=(await api(`/api/runs/${selected}/log`)).text;}catch(e){error(e.message);}}});
function renderRun(state){
  $('status').className=`badge ${state.status}`;$('status').textContent=pretty(state.status);
  $('commits').innerHTML=commitCards(state.revisions);
  const stages=['preparing','building','validating','benchmarking','comparing','complete'];const index=stages.indexOf(state.stage);
  $('stages').innerHTML=stages.map((stage,i)=>`<li class="${i<index?'done':i===index?'current':''}">${i<index?'✓ ':''}${stage}</li>`).join('');
  $('message').textContent=state.message + (state.revisions.baseline.sha===state.revisions.candidate.sha ? ' Same-commit control: differences reflect measurement noise, not a code change.' : '');
  $('counts').textContent=`${state.completed} / ${state.total} timed workloads completed`;
  const seconds=Math.max(0,Math.floor((state.ended||Date.now()/1000)-state.started));
  $('elapsed').textContent=`${Math.floor(seconds/60)}m ${String(seconds%60).padStart(2,'0')}s`;
  $('cancel').classList.toggle('hidden',terminal.includes(state.status));$('cancel').disabled=false;
  if(state.status==='failed'){error(state.message);$('log-details').open=true;}
  if(state.status==='complete'){renderResults(state); if(analysisRun!==state.id){analysisRun=state.id;pollAnalysis();}}
}
const timing=ns=>ns>=1e6?`${(ns/1e6).toFixed(2)} ms`:ns>=1e3?`${(ns/1e3).toFixed(2)} µs`:`${ns.toFixed(1)} ns`;
const delta=value=>`${value>=0?'+':''}${value.toFixed(1)}%`;
function renderResults(state){
  $('results').classList.remove('hidden');
  const rows=state.results;
  $('cards').innerHTML=[['Scenarios measured',rows.length],['Reproducible regressions',rows.filter(x=>x.verdict==='regression').length],['Improvements',rows.filter(x=>x.verdict==='improvement').length],['Inconclusive',rows.filter(x=>x.verdict==='inconclusive').length]].map(([label,value])=>`<div class="card"><small>${label}</small><strong>${value}</strong></div>`).join('');
  $('charts').innerHTML=rows.map(row=>{const max=Math.max(row.baseline_ns,row.candidate_ns);return `<div class="chart-row"><span>${pretty(row.name)}</span><div class="bars" role="img" aria-label="${escape(pretty(row.name))}: baseline ${timing(row.baseline_ns)}, candidate ${timing(row.candidate_ns)}"><div class="bar" style="width:${row.baseline_ns/max*100}%"></div><div class="bar candidate" style="width:${row.candidate_ns/max*100}%"></div></div><b class="${row.verdict==='regression'?'positive':row.verdict==='improvement'?'negative':''}">${delta(row.change_pct)}</b></div>`;}).join('');
  renderTable();
  $('download-report').href=`/api/runs/${state.id}/download/report.md`;$('download-json').href=`/api/runs/${state.id}/download/results.json`;
  const mismatched=history.some(x=>x.environment && JSON.stringify(x.environment)!==JSON.stringify(state.environment));
  $('environment').textContent=`${state.environment.system} · ${state.environment.machine} · ${state.environment.cpus} CPUs\n${state.environment.rustc}\n${state.profiling}${mismatched?'\nHistory includes different environments. Do not compare timings across those runs.':''}`;
  $('environment').style.whiteSpace='pre-line';
}
function renderTable(){
  if(!current?.results)return;
  const rows=[...current.results].sort((a,b)=>$('sort').value==='name'?a.name.localeCompare(b.name):$('sort').value==='time'?b.candidate_ns-a.candidate_ns:b.change_pct-a.change_pct);
  $('rows').innerHTML=rows.map(row=>`<tr><td><button data-scenario="${row.name}">${pretty(row.name)} ↗</button></td><td>${timing(row.baseline_ns)}</td><td>${timing(row.candidate_ns)}</td><td>${delta(row.change_pct)}</td><td><span class="badge ${row.verdict}">${pretty(row.verdict)}</span></td></tr>`).join('');
  $('rows').querySelectorAll('button').forEach(button=>button.onclick=()=>showDetail(button.dataset.scenario));
}
$('sort').onchange=renderTable;
function showDetail(name){
  const row=current.results.find(x=>x.name===name);$('detail').classList.remove('hidden');
  $('detail').innerHTML=`<h3>${pretty(name)}</h3><p>✓ Exact match locations and expected output verified. Times below include Criterion confidence bounds.<br>A regression requires &gt;5% slowdown and separated intervals in all three pairs.</p><div class="table-wrap"><table><thead><tr><th>Pair</th><th>Baseline [bounds]</th><th>Candidate [bounds]</th><th>Change</th></tr></thead><tbody>${row.baseline.map((b,i)=>{const c=row.candidate[i];return `<tr><td>${i+1}</td><td>${timing(b.mean)} [${timing(b.lower)}, ${timing(b.upper)}]</td><td>${timing(c.mean)} [${timing(c.lower)}, ${timing(c.upper)}]</td><td>${delta(row.pair_changes[i])}</td></tr>`;}).join('')}</tbody></table></div>`;
}
$('copy').onclick=async()=>{
  try {const response=await fetch(`/api/runs/${selected}/download/investigate.md`);if(!response.ok)throw new Error('Prompt not available');await navigator.clipboard.writeText(await response.text());$('copy').textContent='Copied ✓';setTimeout(()=>$('copy').textContent='Copy investigation prompt',1800);}catch(e){error(e.message);}
};
// Analysis lives independently of the benchmark result and never changes its verdicts.
let analysisRun=null, analysisTimer=null, analysisAttempt=null, analysisRequest=0;
function stopAnalysis(){
  analysisRun=null;analysisAttempt=null;analysisRequest++;clearTimeout(analysisTimer);
  $('analysis-panel').classList.add('hidden');$('analysis-evidence').classList.add('hidden');
}
$('analyze').onclick=async()=>{
  const id=selected;if(!id)return;error('');$('analyze').disabled=true;
  try{await api(`/api/runs/${id}/analysis`,{});if(id!==selected)return;analysisAttempt=null;analysisRun=id;await pollAnalysis();}
  catch(e){error(e.message);$('analyze').disabled=false;}
};
$('analysis-cancel').onclick=async()=>{
  try{await api(`/api/runs/${selected}/analysis/cancel`,{});$('analysis-cancel').disabled=true;}
  catch(e){error(e.message);}
};
$('analysis-attempt').onchange=()=>{analysisAttempt=$('analysis-attempt').value;pollAnalysis();};
async function pollAnalysis(){
  clearTimeout(analysisTimer);const id=analysisRun, revision=++analysisRequest;if(!id)return;
  try{
    const query=analysisAttempt?`?attempt=${encodeURIComponent(analysisAttempt)}`:'';
    const data=await api(`/api/runs/${id}/analysis${query}`);
    if(id!==selected || revision!==analysisRequest)return;
    const busy=data.attempts.some(x=>x.status==='running');
    $('analyze').disabled=busy; $('analyze').textContent=data.status==='not_started'?'Run agent investigation →':busy?'Agent investigation running…':'Run another investigation →';
    $('analysis-panel').classList.toggle('hidden',data.status==='not_started');
    if(data.status!=='not_started')renderAnalysis(data,id);
    if(busy)analysisTimer=setTimeout(pollAnalysis,1000);
  }catch(e){if(id===selected){error(e.message);analysisTimer=setTimeout(pollAnalysis,2000);}}
}
function renderAnalysis(data,id){
  $('analysis-status').textContent=pretty(data.status);$('analysis-status').className=`badge ${data.status}`;
  $('analysis-message').textContent=data.message;
  const seconds=Math.max(0,Math.floor((data.ended||Date.now()/1000)-data.started));
  $('analysis-elapsed').textContent=`${Math.floor(seconds/60)}m ${seconds%60}s · ${data.model || 'CLI default model (not reported)'} · Read-only`;
  $('analysis-attempt').innerHTML=data.attempts.map(x=>`<option value="${escape(x.id)}" ${x.id===data.id?'selected':''}>${escape(new Date(x.started*1000).toLocaleString())} · ${escape(x.status)}</option>`).join('');
  $('analysis-cancel').classList.toggle('hidden',data.status!=='running');$('analysis-cancel').disabled=false;
  $('analysis-download').classList.toggle('hidden',data.status!=='complete');
  $('analysis-download').href=`/api/runs/${id}/analysis/report?attempt=${encodeURIComponent(data.id)}`;
  $('analysis-outcome').textContent=`Measured outcome: ${data.measured_outcome}`;
  $('analysis-activity').textContent=data.activity.map(x=>`${x.type}: ${x.text}`).join('\n') || 'Waiting for the first CLI event…';
  const result=data.result;
  if(data.status!=='complete'||!result){$('analysis-content').replaceChildren();return;}
  $('analysis-content').innerHTML=`<h3>Summary</h3><p>${escape(result.summary)}</p><h3>What changed</h3><p>${escape(result.changed_behavior)}</p><h3>Possible causes & next experiments</h3><p class="muted">Agent hypotheses, separate from the measured verdict. Confidence is the agent’s assessment.</p>${result.hypotheses.map((h,i)=>`<article class="hypothesis"><div class="section-heading"><h3>${i+1}. ${escape(h.title)}</h3><span class="badge">${escape(h.confidence)} confidence</span></div><p>${escape(h.explanation)}</p><p><strong>Counterevidence:</strong> ${escape(h.counterevidence)}</p><p><strong>Next experiment:</strong> ${escape(h.next_experiment)}</p><div class="evidence-links">${h.evidence.map((r,j)=>`<button class="button secondary" data-hypothesis="${i}" data-reference="${j}">${escape(r.file)}:${r.start}–${r.end}</button>`).join('')}</div></article>`).join('')}<h3>Limitations</h3><ul>${result.limitations.map(x=>`<li>${escape(x)}</li>`).join('')}</ul>`;
  $('analysis-content').querySelectorAll('[data-reference]').forEach(button=>button.onclick=async()=>{
    const ref=result.hypotheses[Number(button.dataset.hypothesis)].evidence[Number(button.dataset.reference)];
    try{
      const value=await api(`/api/runs/${id}/analysis/evidence?${new URLSearchParams(ref)}`);if(selected!==id)return;
      $('evidence-title').textContent=`${value.file}:${value.start}–${value.end}`;
      $('evidence-text').textContent=value.text.split('\n').map((line,i)=>`${value.start+i}  ${line}`).join('\n');
      $('analysis-evidence').classList.remove('hidden');$('analysis-evidence').focus();
    }catch(e){error(e.message);}
  });
}
let versionData={commits:[],refs:[]}, versionSkip=0, versionRequest=0;
let rangeRequest=null, rangeGeneration=0, rangeTimer=null, summaryTimer=null, summaryJob=null;
function resetCommitRange(){rangeGeneration++;rangeRequest=null;summaryJob=null;clearTimeout(rangeTimer);clearTimeout(summaryTimer);$('commit-range-panel').classList.add('hidden');}
function versionOptions(){
  const entries=new Map([...versionData.commits,...(versionData.defaults||[])].map(c=>[c.sha,{...c,names:[]}]));
  for(const ref of versionData.refs){if(!entries.has(ref.sha))entries.set(ref.sha,{sha:ref.sha,subject:'',date:'',names:[]});entries.get(ref.sha).names.push(ref.name);}
  const query=$('version-search').value.toLowerCase();
  for(const side of ['base','candidate']){
    const chosen=$(side).value;
    $(side).innerHTML=[...entries.values()].filter(c=>c.sha===chosen||`${c.names.join(' ')} ${c.sha} ${c.subject} ${c.date}`.toLowerCase().includes(query)).map(c=>`<option value="${escape(c.sha)}">${escape((c.names.length?c.names.join(', ')+' · ':'')+c.sha.slice(0,10)+' · '+c.subject+(c.date?' · '+c.date:''))}</option>`).join('');
    if(entries.has(chosen))$(side).value=chosen;
  }
}
async function loadVersions(more=false){
  const repo=$('repo').value.trim(),seq=++versionRequest;
  $('load-versions').disabled=true;$('older-versions').disabled=true;
  $('versions-note').textContent='Reading local Git versions…';
  if(!more){invalidate();resetCommitRange();$('base').innerHTML='';$('candidate').innerHTML='';versionData={commits:[],refs:[]};versionSkip=0;}
  try{
    const data=await api('/api/revisions',{repo,skip:more?versionSkip:0,demo:$('demo-months').checked});if(seq!==versionRequest||repo!==$('repo').value.trim())return;
    versionData={commits:more?[...versionData.commits,...data.commits]:data.commits,refs:data.refs,defaults:data.defaults};versionSkip=data.next_skip;
    versionOptions();
    if(!more){$('candidate').value=data.head;$('base').value=data.default_base;scheduleRange();}
    $('older-versions').classList.toggle('hidden',!data.has_more);
    $('versions-note').textContent=`${versionData.commits.length} commits loaded · ${data.refs.length} tags/branches · local history`;
  }catch(e){if(seq===versionRequest)$('versions-note').textContent=e.message;}
  finally{if(seq===versionRequest){$('load-versions').disabled=false;$('older-versions').disabled=false;}}
}
$('demo-months').addEventListener('change',()=>loadVersions());
$('repo').addEventListener('change',()=>loadVersions());
$('repo').addEventListener('input',()=>{versionRequest++;invalidate();resetCommitRange();$('base').innerHTML='';$('candidate').innerHTML='';$('load-versions').disabled=false;});
$('load-versions').onclick=()=>loadVersions();$('older-versions').onclick=()=>loadVersions(true);
$('version-search').oninput=versionOptions;
for(const id of ['base','candidate'])$(id).addEventListener('change',()=>{invalidate();scheduleRange();});
function scheduleRange(){resetCommitRange();rangeTimer=setTimeout(()=>{const r=request();if(r.base&&r.candidate)showCommitRange(r);},700);}
async function showCommitRange(input){
  const generation=++rangeGeneration;clearTimeout(summaryTimer);rangeRequest=input;summaryJob=null;
  $('commit-range-panel').classList.remove('hidden');$('commit-range-list').replaceChildren();$('commit-range-count').textContent='';$('commit-summary-status').textContent='Loading commit range…';$('summary-retry').classList.add('hidden');$('summary-cancel').classList.add('hidden');
  try{
    const data=await api('/api/commit-range',{...input,demo:$('demo-months').checked});if(generation!==rangeGeneration)return;
    rangeRequest={repo:data.repo,base:data.base,candidate:data.candidate,demo:data.demo};
    $('commit-range-count').textContent=`${data.commits.length} commits`;
    const prefix=`${data.base.slice(0,12)} → ${data.candidate.slice(0,12)}. `;
    const notes={forward:'Commits introduced after baseline, including the comparison commit. Oldest first.',identical:'Both selections resolve to the same version. No commits between them.',reverse:'Comparison is older than baseline. These are the intervening commits removed when moving from baseline to comparison. Oldest first.',diverged:'These versions diverged. Showing commits reachable from comparison but not baseline (baseline..comparison), including merged branch commits.'};
    $('commit-range-note').textContent=prefix+(data.message||notes[data.relationship]);
    $('commit-range-list').innerHTML=data.commits.map(c=>`<li><div class="commit-row-title"><code>${escape(c.sha.slice(0,12))}</code><strong>${escape(c.subject)}</strong><time>${escape(c.date)}</time></div><p id="summary-${c.sha}" class="commit-one-liner">${data.commits.length?'Waiting for LLM summary…':''}</p></li>`).join('');
    if(!data.commits.length){$('commit-summary-status').textContent=data.relationship==='unavailable'?'Summaries blocked: commit ancestry is unavailable.':'No summaries needed.';return;}
    await generateSummaries(generation);
  }catch(e){if(generation===rangeGeneration)$('commit-summary-status').textContent=e.message;}
}
async function generateSummaries(generation=rangeGeneration){
  if(!rangeRequest)return;
  $('summary-retry').classList.add('hidden');$('commit-summary-status').textContent='Starting LLM summaries…';
  try{const state=await api('/api/commit-summaries',rangeRequest);if(generation!==rangeGeneration)return;summaryJob=state.id;renderSummaries(state,generation);}
  catch(e){if(generation!==rangeGeneration)return;$('commit-summary-status').textContent=e.message;if(e.message.includes('running'))summaryTimer=setTimeout(()=>generateSummaries(generation),3000);else $('summary-retry').classList.remove('hidden');}
}
function renderSummaries(state,generation){
  if(generation!==rangeGeneration)return;
  for(const [sha,line] of Object.entries(state.summaries)){const node=$('summary-'+sha);if(node){node.textContent=line;node.classList.add('ready');}}
  $('commit-summary-status').textContent=`${state.message} · ${Object.keys(state.summaries).length}/${state.commits.length} summarized`;
  $('summary-cancel').classList.toggle('hidden',state.status!=='running');$('summary-cancel').disabled=false;
  $('summary-retry').classList.toggle('hidden',!['failed','cancelled','interrupted'].includes(state.status));
  if(state.status==='running')summaryTimer=setTimeout(async()=>{try{renderSummaries(await api('/api/commit-summaries/'+state.id),generation);}catch(e){if(generation===rangeGeneration){$('commit-summary-status').textContent=e.message;$('summary-retry').classList.remove('hidden');}}},1000);
}
$('summary-retry').onclick=()=>generateSummaries();
$('summary-cancel').onclick=async()=>{try{await api('/api/commit-summaries/cancel',{id:summaryJob});$('summary-cancel').disabled=true;}catch(e){error(e.message);}};
(async()=>{try{const config=await api('/api/config');token=config.token;$('repositories').innerHTML=config.repositories.map(x=>`<option value="${escape(x)}"></option>`).join('');$('repo').value=config.repositories.find(x=>x.endsWith('sds-shared-library-sdsp-568'))||config.repositories[0]||'';await refreshHistory();if(config.active)await openRun(config.active);else await loadVersions();}catch(e){error(e.message);}})();

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');

const repo = path.resolve(__dirname, '../..');
const candidates = process.platform === 'win32'
  ? ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe']
  : ['/usr/bin/chromium', '/usr/bin/google-chrome'];
const browser = candidates.find(fs.existsSync);

test('YouTube panel displays workspace views and grades and saves its session quiz', { skip: !browser, timeout: 45000 }, async () => {
  const graph = { title: 'Lesson', duration_seconds: 30, frame: { content_rect: [0, 0, 1, 1] }, objects: [],
    transcript: [{ seg_id: 's1', start: 5 }], concept_nodes: [{ node_id: 'c1', label: 'Neutralization', prerequisites: [], evidence: { segment_ids: ['s1'], object_ids: [] } }] };
  const cut = { session_id: 'sess_test', status: 'approved', pass_count: 1, critic_score: { safety: 1, coherence: 1, factuality: 1, completeness: 1 }, final_threads: [{ start: 0, end: 30, action: 'keep', label: 'Lesson' }], redaction_masks: [], skipped: [], quiz: [{ question_id: 'q1', stem: 'Question?', options: ['Yes', 'No'] }] };
  const mock = `
    const calls=[]; window.chrome=window.chrome||{};
    chrome.storage={local:{get:async()=>({}),set:()=>{}}};
    chrome.runtime={id:'test',lastError:null,sendMessage:(msg,cb)=>{ calls.push(msg.path); let d=null, ok=true, status=200;
      if(msg.path==='/api/ready') d={ready:true};
      else if(msg.path.startsWith('/api/lookup')) d={ready:true,video_id:'v1'};
      else if(msg.path==='/api/videos/v1/graph') d=${JSON.stringify(graph)};
      else if(msg.path==='/api/learners') d=[{learner_id:'l1',display_name:'Alex',persona:'Expert',preferences:{pace:'standard'},safety_profile:{redaction_level:'off'}}];
      else if(msg.path==='/api/videos/v1/explainers') d=[];
      else if(msg.path==='/api/videos/v1/map') d={items:[{id:'c1',kind:'concept',label:'Neutralization',x:.5,y:.5,t:5}],edges:[]};
      else if(msg.path==='/api/videos/v1/ask') d={answer:'An answer',retrieved:['c1'],citations:[],suggest:[],agent_trace:[],found_in_video:true};
      else if(msg.path==='/api/sessions' && msg.method==='POST') d={session_id:'sess_test'};
      else if(msg.path==='/api/sessions/sess_test') d=${JSON.stringify(cut)};
      else if(msg.path.startsWith('/api/channels/sess_test/latest')) d={events:[{kind:'agent_done',data:{agent:'loom-curator',latency_ms:3}},{kind:'agent_note',data:{agent:'loom-curator',text:'Thread ready',items:[]}}]};
      else if(msg.path==='/api/sessions/sess_test/quiz/q1/answer') d={correct:true,correct_index:0,rationale:'Correct',evidence:[{start:5}]};
      else if(msg.path==='/api/sessions/sess_test/finish') d={mastery_updates:[{label:'Neutralization',before:.2,after:.48}]};
      else { ok=false;status=404;d={detail:msg.path}; }
      setTimeout(()=>cb({ok,status,data:d}),0);
    }};
    window.requestAnimationFrame=()=>0; window.cancelAnimationFrame=()=>{};
    async function waitFor(f,label){for(let i=0;i<100;i++){let v=f();if(v)return v;await new Promise(r=>setTimeout(r,20));}throw Error('missing '+label)}
    window.addEventListener('load',async()=>{try{
      const $=s=>document.querySelector(s);
      (await waitFor(()=>$('[data-act="weave"]'),'viewer')).click();
      await waitFor(()=>$('[data-act="lessonquiz"]'),'cut');
      $('[data-tab="loom"]').click(); if(!$('[data-pane="loom"]').textContent.includes('Thread ready')) throw Error('agent activity');
      $('[data-tab="graph"]').click(); if(!$('[data-pane="graph"]').textContent.includes('Neutralization')) throw Error('graph');
      $('[data-tab="ask"]').click(); $('.loom-ask textarea').value='Explain'; $('[data-act="answer"]').click();
      await waitFor(()=>$('.loom-answer'),'answer'); $('[data-tab="map"]').click();
      await waitFor(()=>$('[data-pane="map"] svg'),'map'); if(!$('[data-pane="map"]').textContent.includes('your question')) throw Error('map highlight');
      $('[data-tab="cut"]').click(); $('[data-act="lessonquiz"]').click();
      (await waitFor(()=>$('[data-act="answerq"]'),'quiz')).click();
      const save=await waitFor(()=>{let b=$('[data-act="save-mastery"]');return b&&!b.disabled&&b},'save'); save.click();
      await waitFor(()=>document.body.textContent.includes('Mastery saved'),'mastery');
      if(!calls.includes('/api/sessions/sess_test/quiz/q1/answer')||calls.includes('/api/quiz/q1/answer'))throw Error('wrong grading route');
      if(!calls.includes('/api/sessions/sess_test/finish'))throw Error('no mastery save');
      $('[data-tab="cut"]').click(); $('[data-act="lessonquiz"]').click();
      const newest=document.querySelector('.loom-result-body');
      if(!newest.querySelector('[data-act="answerq"]').disabled||!newest.querySelector('[data-act="save-mastery"]').disabled)throw Error('saved quiz was re-enabled');
      document.title='WORKSPACE PASS';
    }catch(e){document.title='WORKSPACE FAIL '+e.message;}});`;
  const page = `<!doctype html><html><head><title>WAITING</title><link rel="stylesheet" href="/content.css"><script>${mock}</script></head><body><div id="movie_player"><video class="html5-main-video"></video></div><script src="/rle.js"></script><script src="/scene.js"></script><script src="/views.js"></script><script src="/content.js"></script></body></html>`;
  const server = http.createServer((req, res) => {
    const name = new URL(req.url, 'http://localhost').pathname.slice(1);
    if (name === 'watch') { res.writeHead(200, { 'content-type': 'text/html' }); res.end(page); return; }
    if (['content.css', 'rle.js', 'scene.js', 'views.js', 'content.js'].includes(name)) { res.writeHead(200, { 'content-type': name.endsWith('.css') ? 'text/css' : 'text/javascript' }); res.end(fs.readFileSync(path.join(repo, 'extension', name))); return; }
    res.writeHead(404); res.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'loom-extension-test-'));
  try {
    const args = ['--headless=new', '--disable-gpu', '--no-sandbox', '--disable-background-networking', `--user-data-dir=${profile}`, '--virtual-time-budget=10000', '--dump-dom', `http://127.0.0.1:${server.address().port}/watch?v=test`];
    const child = spawn(browser, args, { windowsHide: true });
    let stdout = '', stderr = '';
    child.stdout.on('data', data => { stdout += data; });
    child.stderr.on('data', data => { stderr += data; });
    const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    assert.equal(code, 0, stderr.slice(-1000));
    assert.match(stdout, /<title>WORKSPACE PASS<\/title>/, stdout.match(/<title>.*?<\/title>/)?.[0] || stderr.slice(-1000));
  } finally {
    await new Promise(resolve => server.close(resolve));
    const resolvedProfile = fs.realpathSync(profile);
    const tempRoot = fs.realpathSync(os.tmpdir());
    if (path.dirname(resolvedProfile) !== tempRoot || !path.basename(resolvedProfile).startsWith('loom-extension-test-')) throw new Error('Unexpected test profile path');
    fs.rmSync(resolvedProfile, { recursive: true, force: true, maxRetries: 4, retryDelay: 100 });
  }
});

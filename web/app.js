'use strict';
const $ = selector => document.querySelector(selector);
const token = $('meta[name="app-token"]').content;
const EXAMPLE = 'https://x.com/i/status/2120074597475496359';
let currentPost = null, busy = false, legalName = null;
let config = {desktop:false, conversion:false, webProcessing:'browser'};
let configLoaded = false, activeDownload = null, activePreview = null;
let language = 'en';
const downloads = new Map();
const MAX_MEDIA_BYTES = 256 * 1024 * 1024;
let browserDownloads = 0;
let themePreference='system';
try{const savedTheme=localStorage.getItem('dongdong-theme');if(['light','dark'].includes(savedTheme))themePreference=savedTheme;}catch{}
const systemTheme=matchMedia('(prefers-color-scheme: dark)');
function matchLanguage(value){
  if(LOCALES[value])return value;
  const lower=String(value||'').toLowerCase();
  if(lower.startsWith('zh'))return /tw|hk|mo|hant/.test(lower)?'zh-TW':'zh-CN';
  return LANGUAGES.find(([code])=>code.toLowerCase()===lower.split('-')[0])?.[0];
}
try{language=matchLanguage(localStorage.getItem('xdownload-language'))||navigator.languages.map(matchLanguage).find(Boolean)||'en';}catch{language=matchLanguage(navigator.language)||'en';}
function t(key, values={}){return String(LOCALES[language][key]??LOCALES.en[key]??LOCALES[language].serviceError).replace(/\{(\w+)\}/g,(_,name)=>values[name]??'');}
function el(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;}
function icon(name){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),use=document.createElementNS(svg.namespaceURI,'use');svg.setAttribute('aria-hidden','true');svg.setAttribute('viewBox','0 0 24 24');use.setAttribute('href','#'+name);svg.append(use);return svg;}
function label(node,key,values={}){node.dataset.i18n=key;node.dataset.values=JSON.stringify(values);node.textContent=t(key,values);return node;}
function button(key,cls,action,values={},iconName){const node=el('button',cls);node.type='button';if(iconName)node.append(icon(iconName));node.append(label(el('span'),key,values));node.onclick=action;return node;}
function status(key,kind='info'){const box=$('#status');box.hidden=!key;box.className='status '+kind;label(box.querySelector('span'),key||'serviceError');box.querySelector('use').setAttribute('href',kind==='loading'?'#spinner':'#info');}
function parsing(active){const submit=$('#submit');submit.disabled=active;submit.classList.toggle('loading',active);submit.setAttribute('aria-busy',String(active));label(submit.querySelector('span'),active?'parsing':'parse');submit.querySelector('use').setAttribute('href',active?'#spinner':'#arrow');}
function applyTheme(){
  const theme=themePreference==='system'?(systemTheme.matches?'dark':'light'):themePreference;
  document.documentElement.dataset.theme=theme;
  $('#theme-toggle use').setAttribute('href','#'+(themePreference==='system'?'system':theme==='dark'?'moon':'sun'));
  $('#theme-toggle').setAttribute('aria-label',t('appearance')+' · '+t({light:'themeLight',dark:'themeDark',system:'themeSystem'}[themePreference]));
  $('#theme-toggle').title=t('appearance');
  document.querySelectorAll('[data-theme-choice]').forEach(node=>node.setAttribute('aria-pressed',String(node.dataset.themeChoice===themePreference)));
  document.querySelectorAll('meta[name="theme-color"]').forEach(node=>node.content=theme==='dark'?'#181817':'#faf8f4');
}
document.querySelectorAll('[data-theme-choice]').forEach(node=>node.onclick=()=>{themePreference=node.dataset.themeChoice;try{localStorage.setItem('dongdong-theme',themePreference);}catch{}applyTheme();$('#theme-menu').open=false;$('#theme-toggle').focus();});
systemTheme.addEventListener('change',()=>{if(themePreference==='system')applyTheme();});
document.addEventListener('click',event=>{if(!$('#theme-menu').contains(event.target))$('#theme-menu').open=false;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('#theme-menu').open){$('#theme-menu').open=false;$('#theme-toggle').focus();}});
function copyrightYear(){const year=Math.max(2026,new Date().getFullYear());$('#copyright-year').textContent=year===2026?'2026':'2026–'+year;}
copyrightYear();document.addEventListener('visibilitychange',()=>{if(!document.hidden)copyrightYear();});setInterval(copyrightYear,60*60*1000);
function translatePage(){
  document.documentElement.lang=language;document.documentElement.dir=['ar','he','fa'].includes(language)?'rtl':'ltr';document.title='东东下载 · '+t('title');$('meta[name="description"]').content=t('title');
  document.querySelectorAll('[data-i18n]').forEach(node=>node.textContent=t(node.dataset.i18n,JSON.parse(node.dataset.values||'{}')));
  document.querySelectorAll('[data-i18n-label]').forEach(node=>node.setAttribute('aria-label',t(node.dataset.i18nLabel)));
  $('#language-name').textContent=LANGUAGES.find(([code])=>code===language)[1];$('#language-button').setAttribute('aria-label',t('language')+' · '+$('#language-name').textContent);
  document.querySelectorAll('[data-language]').forEach(node=>node.setAttribute('aria-pressed',String(node.dataset.language===language)));
  const faq=$('#faq-list');faq.replaceChildren();LOCALES[language].faq.forEach(([question,answer])=>{const detail=el('details');detail.append(el('summary','',question),el('p','',answer));faq.append(detail);});
  applyTheme();if(currentPost)render();if(legalName)renderLegal();
}
async function api(path,data){
  let response,body;try{response=await fetch('/api/'+path,{method:data?'POST':'GET',headers:{'X-App-Token':token,...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});body=await response.json();}catch{throw Error('serviceError');}
  if(!response.ok){if(body.diagnostics)console.warn('Dongdong',body.diagnostics);throw Error(body.error||'serviceError');}return body;
}
function duration(seconds){return seconds?Math.floor(seconds/60)+':'+String(Math.floor(seconds%60)).padStart(2,'0'):'';}
function inputPlatform(){
  let host='';try{host=new URL($('#url').value.match(/https?:\/\/[^\s<>]+/i)?.[0]||'').hostname;}catch{}
  const platform=['instagram.com','www.instagram.com','m.instagram.com'].includes(host)?'instagram':['x.com','www.x.com','twitter.com','www.twitter.com','mobile.twitter.com','m.twitter.com'].includes(host)?'x':'';
  const mark=$('#platform-mark');mark.replaceChildren(platform?el('span','',platform==='instagram'?'Instagram':'X'):icon('link'));mark.title=platform==='instagram'?'Instagram':platform?'X':'';
  mark.classList.toggle('platform-name',platform==='instagram');
  mark.setAttribute('aria-label',mark.title);mark.setAttribute('aria-hidden',String(!platform));
}
$('#example').onclick=()=>{$('#url').value=EXAMPLE;inputPlatform();$('#url').focus();};
$('#paste').onclick=async()=>{try{$('#url').value=await navigator.clipboard.readText();inputPlatform();$('#url').focus();}catch{status('clipboardError');$('#url').focus();}};
const downloadDialog=$('#download-dialog');
$('#windows-link').onclick=()=>$('#windows-dialog').showModal();
$('#url').addEventListener('input',()=>{status('');inputPlatform();});
inputPlatform();
$('#download-form').onsubmit=async e=>{
  e.preventDefault();if(busy||activeDownload)return;if(!configLoaded){status('serviceError','error');return;}busy=true;parsing(true);$('#url').disabled=true;status('');
  try{currentPost=await api('parse',{url:$('#url').value});for(const [key,state] of downloads)if(!state.active)downloads.delete(key);render();status('');downloadDialog.showModal();downloadDialog.scrollTop=0;}
  catch(error){status(error.message,'error');}finally{busy=false;parsing(false);$('#url').disabled=false;}
};
function bindDownload(node,key,values,iconName,indices,mode,quality,post){
  const id=[post.id,indices.join('-'),mode,quality].join('_');
  node.classList.add('download-action');node.dataset.downloadId=id;
  node.dataset.actionKey=key;node.dataset.actionValues=JSON.stringify(values);node.dataset.actionIcon=iconName||'download';
  node.onclick=()=>startDownload(indices,mode,quality,post,id);
  paintDownload(node,downloads.get(id));return node;
}
function downloadButton(key,cls,indices,mode,quality,post,values={},iconName){return bindDownload(button(key,cls,()=>{},values,iconName),key,values,iconName,indices,mode,quality,post);}
function paintDownload(node,state){
  const values=JSON.parse(node.dataset.actionValues),key=node.dataset.actionKey;
  node.disabled=Boolean(activeDownload)||node.dataset.unavailable==='true';
  node.classList.toggle('is-downloading',Boolean(state?.active));node.classList.toggle('download-failed',Boolean(state?.error));
  node.classList.toggle('download-complete',Boolean(state?.completing));node.style.setProperty('--download-progress',(state?.progress||0)+'%');
  node.setAttribute('aria-busy',String(Boolean(state?.active)));
  node.title=state?.message?t(state.message,state.values||{}):'';node.setAttribute('aria-label',t(key,values)+(node.title?' · '+node.title:''));
  node.replaceChildren(icon(state?.active?'spinner':state?.error?'info':state?.completing?'check':node.dataset.actionIcon));
  const text=label(el('span'),state?.active?state.message:state?.error?'retry':state?.completing?'completed':key,state?.active?state.values||{}:values);
  node.append(text);
  if(state?.error){const note=label(el('small','button-error'),state.message);node.append(note);}
}
function paintDownloads(id){document.querySelectorAll('[data-download-id]').forEach(node=>{if(!id||node.dataset.downloadId===id)paintDownload(node,downloads.get(node.dataset.downloadId));});}
function stopPreview(){
  if(!activePreview)return;
  const {video,thumb,play}=activePreview;activePreview=null;
  video.onerror=null;video.pause();video.removeAttribute('src');video.load();video.remove();
  thumb.classList.remove('is-playing');play.hidden=false;
}
function addPreview(thumb,item){
  if(config.desktop||config.webProcessing!=='browser'||!['video','gif'].includes(item.kind))return;
  const format=item.formats.find(value=>value.ext==='mp4'&&value.url);if(!format)return;
  let source;try{source=directMediaURL(format.url);}catch{return;}
  const note=label(el('p','preview-error'),'playbackError');note.hidden=true;note.setAttribute('role','status');
  const play=el('button','preview-play');play.type='button';play.dataset.i18nLabel='playVideo';play.setAttribute('aria-label',t('playVideo'));play.title=t('playVideo');play.append(icon('play'));
  play.onclick=()=>{
    stopPreview();note.hidden=true;
    const video=el('video');video.controls=true;video.playsInline=true;video.preload='none';video.crossOrigin='anonymous';video.muted=item.kind==='gif';video.loop=item.kind==='gif';video.setAttribute('aria-label',t('playVideo'));
    activePreview={video,thumb,play};play.hidden=true;thumb.classList.add('is-playing');thumb.append(video);
    const failed=()=>{if(activePreview?.video!==video)return;stopPreview();note.hidden=false;};
    video.onerror=failed;video.src=source.href;video.play().catch(failed);
  };
  thumb.append(play,note);
}
function render(){
  stopPreview();const items=currentPost.media,grid=$('#media-grid');grid.replaceChildren();$('#download-all').hidden=items.length<2;
  bindDownload($('#download-all'),'allZip',{},'download',items.map(item=>item.index),'original',0,currentPost);
  const meta=$('#post-meta');meta.replaceChildren();if(currentPost.avatar){const avatar=el('img','author-avatar');avatar.src=currentPost.avatar;avatar.alt='';avatar.onerror=()=>avatar.remove();meta.append(avatar);}
  const handle=String(currentPost.handle||'').replace(/^@/,''),instagram=currentPost.platform==='instagram';
  const validHandle=(instagram?/^[A-Za-z0-9_.]{1,30}$/:/^[A-Za-z0-9_]{1,15}$/).test(handle);
  const copy=el('div','post-copy'),author=el(validHandle?'a':'strong','post-author',currentPost.author||(instagram?'Instagram':'X')),description=el('p');
  if(author.tagName==='A'){author.href=(instagram?'https://www.instagram.com/':'https://x.com/')+encodeURIComponent(handle);author.target='_blank';author.rel='noopener noreferrer';}
  const postLink=el('a','post-link',String(currentPost.title).replace(/\r\n?/g,'\n').replace(/\n[\t ]*\n+/g,'\n'));postLink.href=instagram?'https://www.instagram.com/p/'+encodeURIComponent(currentPost.id.replace(/^IG_/,''))+'/':'https://x.com/i/status/'+encodeURIComponent(currentPost.id);postLink.target='_blank';postLink.rel='noopener noreferrer';description.append(postLink);
  author.dir='auto';description.dir='auto';description.id='post-text';
  const expand=button('expandPost','post-toggle',()=>{const expanded=description.classList.toggle('expanded');expand.setAttribute('aria-expanded',String(expanded));label(expand.querySelector('span'),expanded?'collapsePost':'expandPost');});expand.hidden=true;expand.setAttribute('aria-expanded','false');expand.setAttribute('aria-controls','post-text');copy.append(author,description,expand);meta.append(copy);
  requestAnimationFrame(()=>{if(description.isConnected)expand.hidden=description.scrollHeight<=description.clientHeight+1;});
  items.forEach(item=>{
    const post=currentPost,card=el('article','media-card'),thumb=el('div','thumbnail');
    if(item.preview){const img=el('img');img.src=item.preview;img.alt=item.kind==='gif'?'GIF':t(item.kind);img.loading='lazy';img.onerror=()=>{img.remove();thumb.append(label(el('span'),'previewUnavailable'));};thumb.append(img);}
    const f=item.formats[0];
    thumb.append(el('span','media-badge',item.kind==='gif'?'GIF / MP4':String(f.ext).toUpperCase()));if(item.duration)thumb.append(el('span','duration',duration(item.duration)));
    addPreview(thumb,item);
    card.setAttribute('aria-label',(item.kind==='gif'?'GIF':t(item.kind))+' '+(item.index+1));
    card.append(thumb);const info=el('div','media-info'),details=el('div','media-details'),controls=el('div','media-controls');details.append(el('h3','media-title',(item.kind==='gif'?'GIF':t(item.kind))+' '+String(item.index+1).padStart(2,'0')),el('p','media-sub',f.width&&f.height?f.width+' × '+f.height:''));
    const row=el('div','download-row');item.formats.forEach((fmt,i)=>row.append(downloadButton(item.kind==='photo'?'downloadPhoto':fmt.label==='original'?'downloadVideo':'downloadMp4','primary',[item.index],'original',i,post,{quality:fmt.label},'download')));controls.append(row);
    const extras=el('div','extra-actions');
    const conversionUnavailable=!config.desktop&&config.webProcessing==='browser'?'localProcessingUnavailable':'noFfmpeg';
    if(item.kind==='gif'){const convert=downloadButton('convertGif','secondary',[item.index],'gif',0,post);convert.dataset.unavailable=String(!config.conversion);convert.disabled=convert.disabled||!config.conversion;convert.title=config.conversion?'GIF · 640 px · 12 fps · ≤ 120 s':t(conversionUnavailable);extras.append(convert);}
    if(item.kind==='video'&&item.has_audio!==false){const convert=downloadButton('convertMp3','secondary',[item.index],'mp3',0,post,{},'audio');convert.dataset.unavailable=String(!config.conversion);convert.disabled=convert.disabled||!config.conversion;if(!config.conversion)convert.title=t(conversionUnavailable);extras.append(convert);}
    if(item.kind!=='photo'&&item.preview)extras.prepend(downloadButton('cover','secondary',[item.index],'cover',0,post,{},'photo'));
    controls.append(extras);info.append(details,controls);card.append(info);grid.append(card);
  });
}
async function save(job,transfer){
  if(transfer.controller.signal.aborted)throw Error('cancelled');
  if(config.desktop){if(!window.pywebview?.api)throw Error('serviceError');const result=await window.pywebview.api.save_file(job.id);if(result.error)throw Error(result.error);transfer.message=result.cancelled?'cancelled':'saved';transfer.values={name:result.name||''};transfer.cancelled=Boolean(result.cancelled);return !result.cancelled;}
  let response;try{response=await fetch('/api/files/'+job.id,{headers:{'X-App-Token':token},signal:transfer.controller.signal});}catch{throw Error(transfer.controller.signal.aborted?'cancelled':'downloadError');}
  if(!response.ok){let code='downloadError';try{code=(await response.json()).error||code;}catch{}throw Error(code);}
  let blob;try{blob=await response.blob();}catch{throw Error('downloadError');}const state=await api('jobs/'+job.id);if(state.status!=='done')throw Error(state.message||'downloadError');
  if(transfer.controller.signal.aborted)throw Error('cancelled');
  const url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download=job.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);transfer.message='browserSaved';transfer.values={name:job.filename};return true;
}
function directMediaURL(source){
  let url;try{url=new URL(source);}catch{throw Error('expired');}
  const allowedHost=['video.twimg.com','pbs.twimg.com'].includes(url.hostname)||/^(?:scontent|instagram)[a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:cdninstagram\.com|fbcdn\.net)$/.test(url.hostname);
  if(url.protocol!=='https:'||!allowedHost||url.username||url.password||url.port)throw Error('invalidSelection');
  return url;
}
async function receiveMedia(source,remaining,onProgress,signal){
  if(signal.aborted)throw Error('cancelled');
  const url=directMediaURL(source);
  const controller=new AbortController();
  const cancel=()=>controller.abort();signal.addEventListener('abort',cancel,{once:true});
  let idle=setTimeout(()=>controller.abort(),20000);
  const deadline=setTimeout(()=>controller.abort(),10*60*1000);
  try{
    const response=await fetch(url.href,{mode:'cors',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer',signal:controller.signal});
    if(!response.ok)throw Error(response.status===403?'mediaAccessDenied':response.status===429?'mediaRateLimited':[401,404,410].includes(response.status)?'expired':'downloadError');
    const total=Number(response.headers.get('Content-Length'))||0;
    if(total>remaining)throw Error('sizeError');
    const type=(response.headers.get('Content-Type')||'').split(';')[0];
    if(!/^(video\/mp4|image\/[a-z0-9.+-]+|application\/octet-stream)$/i.test(type))throw Error('downloadError');
    const reader=response.body.getReader(),chunks=[];let received=0;
    for(;;){
      clearTimeout(idle);idle=setTimeout(()=>controller.abort(),30000);
      const {done,value}=await reader.read();if(done)break;
      received+=value.byteLength;if(received>remaining)throw Error('sizeError');
      chunks.push(value);onProgress(received,total);
    }
    if(!received)throw Error('downloadError');
    return new Blob(chunks,{type});
  }catch(error){
    if(signal.aborted)throw Error('cancelled');
    if(error.name==='AbortError'||error instanceof TypeError)throw Error('mediaConnectionError');
    throw error;
  }finally{clearTimeout(idle);clearTimeout(deadline);controller.abort();signal.removeEventListener('abort',cancel);}
}
async function saveInBrowser(indices,mode,quality,post,state,id){
  if(browserDownloads>=2)throw Error('busyError');
  browserDownloads++;
  try{
    const entries=[],prefix=post.platform==='instagram'?post.id:'X_'+post.id;let received=0,lastPaint=0;
    for(const [position,index] of indices.entries()){
      const item=post.media.find(value=>value.index===index);
      const format=mode==='cover'?item?.cover:item?.formats[indices.length===1?quality:0];
      if(!format?.url)throw Error('expired');
      state.message='connecting';state.values={};paintDownloads(id);
      const blob=await receiveMedia(format.url,MAX_MEDIA_BYTES-received,(loaded,total)=>{
        if(total){
          state.measured=true;state.progress=(position+Math.min(1,loaded/total))/indices.length*75;
          state.message='downloadProgress';state.values={percent:Math.min(99,Math.floor(loaded/total*100))};
        }else{state.message='receiving';state.values={};}
        if(performance.now()-lastPaint>200){lastPaint=performance.now();paintDownloads(id);}
      },state.controller.signal);
      received+=blob.size;entries.push({name:prefix+'_'+(index+1)+(mode==='cover'?'_cover':'')+'.'+format.ext,blob});
      state.progress=(position+1)/indices.length*75;state.measured=true;paintDownloads(id);
    }
    let blob=entries[0].blob,filename=entries[0].name;
    if(mode==='mp3'||mode==='gif'){
      if(!window.BrowserMedia)throw Error('localProcessingUnavailable');
      state.message=mode==='mp3'?'convertingMp3':'convertingGif';state.values={};paintDownloads(id);
      blob=await BrowserMedia.convert(blob,mode,percent=>{state.progress=75+Math.min(100,percent)*.2;paintDownloads(id);},state.controller.signal);
      filename=prefix+'_'+(indices[0]+1)+'.'+mode;
    }else if(entries.length>1){
      if(!window.BrowserMedia)throw Error('localProcessingUnavailable');
      state.message='packing';state.values={number:entries.length,total:entries.length};paintDownloads(id);
      blob=await BrowserMedia.pack(entries,percent=>{state.progress=75+Math.min(100,percent)*.2;paintDownloads(id);},state.controller.signal);
      filename=prefix+'_all.zip';
    }
    if(blob.size>MAX_MEDIA_BYTES)throw Error('sizeError');
    if(state.controller.signal.aborted)throw Error('cancelled');
    const url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    state.message='browserSaved';state.values={name:filename};return true;
  }finally{browserDownloads--;}
}
async function startDownload(indices,output,quality,post,id){
  if(!post||activeDownload)return;
  if(!await confirmMediaDownload())return;
  if(activeDownload)return;
  const state={active:true,message:'creating',values:{},progress:4,controller:new AbortController()};activeDownload=state;downloads.set(id,state);paintDownloads();
  const started=performance.now(),animation=setInterval(()=>{
    if(state.measured)return;
    state.progress=Math.max(state.progress,4+(config.webProcessing==='browser'&&!config.desktop?66:84)*(1-Math.exp(-(performance.now()-started)/24000)));
    document.querySelectorAll('[data-download-id]').forEach(node=>{if(node.dataset.downloadId===id)node.style.setProperty('--download-progress',state.progress+'%');});
  },250);
  try{
    if(!config.desktop&&config.webProcessing==='browser'){
      state.saved=await saveInBrowser(indices,output,quality,post,state,id);return;
    }
    const created=await api('jobs',{post:post.id,indices,mode:output,quality});state.jobId=created.id;
    if(state.controller.signal.aborted){await api('jobs/'+created.id+'/cancel',{});throw Error('cancelled');}
    let finished=false,transferError=null,saved=false;
    const transfer=save(created,state).then(value=>{saved=value;}).catch(error=>{transferError=error;}).finally(()=>{finished=true;});
    while(!finished){try{const job=await api('jobs/'+created.id);if(!finished){state.message=job.message==='connecting'&&job.progress>0?'receiving':job.message;state.values={number:job.number,total:job.total};const progress=job.message==='packing'?((job.number-1)+(job.progress||0)/100)/job.total*100:job.progress;state.progress=Math.max(state.progress,Math.min(95,progress||0));paintDownloads(id);}}catch{if(!finished){state.message='receiving';paintDownloads(id);}}await new Promise(resolve=>setTimeout(resolve,1000));}
    await transfer;if(transferError){try{const job=await api('jobs/'+created.id);if(job.status==='error')transferError=Error(job.message);}catch{}throw transferError;}
    state.saved=saved;
  }catch(error){state.cancelled=state.controller.signal.aborted||error.message==='cancelled';state.error=!state.cancelled;state.message=state.cancelled?'cancelled':error.message;}
  finally{clearInterval(animation);state.active=false;activeDownload=null;state.progress=state.saved?100:0;state.completing=Boolean(state.saved);if($('#cancel-download-dialog').open)$('#cancel-download-dialog').close();paintDownloads();if(state.saved)setTimeout(()=>{if(downloads.get(id)===state){downloads.delete(id);paintDownloads(id);}},1800);}
}
function requestDownloadClose(){
  if(!activeDownload){downloadDialog.close();return;}
  const dialog=$('#cancel-download-dialog');if(dialog.open)return;dialog.returnValue='';dialog.showModal();
}
$('#cancel-download-dialog').addEventListener('close',()=>{
  if($('#cancel-download-dialog').returnValue!=='cancel')return;
  const state=activeDownload;
  if(state){state.controller.abort();if(state.jobId)api('jobs/'+state.jobId+'/cancel',{}).catch(()=>{});}
  downloadDialog.close();
});
downloadDialog.addEventListener('cancel',event=>{if(activeDownload){event.preventDefault();requestDownloadClose();}});
downloadDialog.addEventListener('close',stopPreview);
window.addEventListener('pagehide',stopPreview);
const rightsDialog=$('#rights-dialog');
$('#rights-check').onchange=()=>{$('#rights-confirm').disabled=!$('#rights-check').checked;};
function confirmMediaDownload(){
  if(rightsDialog.open)return Promise.resolve(false);
  $('#rights-check').checked=false;$('#rights-confirm').disabled=true;rightsDialog.returnValue='';
  return new Promise(resolve=>{rightsDialog.addEventListener('close',()=>resolve(rightsDialog.returnValue==='confirm'&&$('#rights-check').checked),{once:true});rightsDialog.showModal();});
}
const legalDialog=$('#legal-dialog');
function renderLegal(){
  const title=$('#legal-title'),copy=$('#legal-copy');copy.replaceChildren();
  if(legalName==='about'){
    delete title.dataset.i18n;delete title.dataset.values;
    title.textContent='东东下载'+(config.desktop?' · '+(config.version||'1.1.0'):'');
  }else label(title,legalName);
  LOCALES[language].legal[legalName].forEach(text=>copy.append(el('p','',text)));
  if(legalName==='privacy'&&config.desktop)copy.append(label(el('p'),'updatePrivacy'));
  if(legalName==='about'&&config.desktop){
    const result=el('div','update-result');result.setAttribute('role','status');
    const check=button('checkUpdates','secondary',async()=>{
      check.disabled=true;result.replaceChildren(label(el('p'),'checkingUpdates'));
      try{
        const update=await api('check-update',{});result.replaceChildren(label(el('p'),update.status,{version:update.version}));
        if(update.status==='updateAvailable'){
          const link=label(el('a','secondary'),'openRelease');link.href=update.url;link.target='_blank';link.rel='noopener noreferrer';result.append(link);
        }
      }catch(error){result.replaceChildren(label(el('p'),error.message));}
      finally{check.disabled=false;}
    });
    copy.append(check,result);
  }
}
function showLegal(name){if(!['about','terms','privacy','disclaimer'].includes(name))return;legalName=name;renderLegal();legalDialog.showModal();legalDialog.scrollTop=0;}
document.querySelectorAll('[data-legal]').forEach(link=>link.onclick=e=>{e.preventDefault();showLegal(link.dataset.legal);});
document.querySelector('.legal-links [data-i18n="contact"]').onclick=event=>{event.preventDefault();$('#contact-status').hidden=true;$('#contact-dialog').showModal();};
$('#copy-email').onclick=async()=>{const note=$('#contact-status');try{await navigator.clipboard.writeText($('#contact-email').value);label(note,'emailCopied');}catch{$('#contact-email').focus();$('#contact-email').select();label(note,'emailCopyFailed');}note.hidden=false;};
document.querySelectorAll('dialog').forEach(dialog=>{const close=()=>dialog===downloadDialog?requestDownloadClose():dialog.close();dialog.querySelector('.close').onclick=close;dialog.onclick=e=>{if(e.target!==dialog)return;const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();};});
const languageDialog=$('#language-dialog');$('#language-button').onclick=()=>languageDialog.showModal();
LANGUAGES.forEach(([code,name])=>{const node=el('button','',name);node.type='button';node.lang=code;node.dir='auto';node.dataset.language=code;node.onclick=()=>{language=code;try{localStorage.setItem('xdownload-language',code);}catch{}translatePage();languageDialog.close();};$('#language-list').append(node);});
translatePage();showLegal(new URLSearchParams(location.search).get('info'));
if(location.protocol==='file:'){status('fileMode','error');$('#submit').disabled=true;}
else {$('#submit').disabled=true;api('config').then(value=>{config=value;configLoaded=true;$('#submit').disabled=false;$('#version').textContent=config.version;$('#desktop-version').hidden=!config.desktop;$('#windows-link').hidden=config.desktop||!config.desktopDownload;if(currentPost)render();if(legalName)renderLegal();}).catch(()=>status('serviceError','error'));}

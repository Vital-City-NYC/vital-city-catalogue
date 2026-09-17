const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../press/index.html'),'utf8');
const source=html.match(/<script>\s*const \$=s=>[\s\S]*?<\/script>/)[0].replace(/^<script>|<\/script>$/g,'');
function harness(){
  const elements=new Map(), lists=new Map();
  const element=id=>{if(!elements.has(id)) elements.set(id,{value:'',checked:false,style:{},textContent:'',innerHTML:'',addEventListener(){},classList:{toggle(){}}});return elements.get(id);};
  const context=vm.createContext({console,URL,Set,Map,setTimeout(){},localStorage:{getItem(){return null}},window:{},document:{querySelector:element,querySelectorAll:s=>lists.get(s)||[],documentElement:{classList:{toggle(){}}},body:{classList:{toggle(){}}}}});
  vm.runInContext(source,context);
  return {run:s=>vm.runInContext(s,context),element,lists};
}
let passed=0;
function test(name,fn){fn();passed++;console.log('PASS',name);}
const setup=`OUT={nyt:{id:'nyt',pin:true,tier:1,size:3,name:'Times',medium:'print'},post:{id:'post',core:true,tier:1,size:3,name:'Post',medium:'print'}}; DATA={outlets:Object.values(OUT),people:[]};`;
test('accent and apostrophe insensitive names; name matches are not clip claims',()=>{
 const h=harness();h.run(setup+`DATA.people=[{id:'anna',name:'Anna Kodé',outlet:'nyt',story_count:80}];`);
 assert.equal(h.run(`rank({text:'Anna Kode',words:[],beats:{}})[0].nameMatch`),true);
 assert.equal(h.run(`rank({text:'Anna Kode',words:[],beats:{}})[0].clips`),0);
 assert.equal(h.run(`searchText('O’Neill')`),"o'neill");
 h.element('#dq').value='anna kode';assert.equal(h.run('dirMatches().length'),1);
});
test('Times matched reporters bypass filters; ordinary outlets do not',()=>{
 const h=harness();h.run(setup+`BEATS={housing:{terms:['housing'],label:'Housing',priority:3}};BEATRE={'housing|housing':beatRe('housing')};
 DATA.people=[{id:'t',name:'Times Person',outlet:'nyt',tier:1,active:true,story_count:5,beats:[{id:'housing',label:'Housing',count:1,examples:[]}]},{id:'p',name:'Post Person',outlet:'post',tier:1,active:true,story_count:5,beats:[{id:'housing',label:'Housing',count:1,examples:[]}]}];`);
 h.element('#q').value='housing';h.element('#fEmail').checked=true;h.element('#fVC').checked=true;
 h.run('runQuery()');assert.match(h.element('#results').innerHTML,/Times Person/);assert.doesNotMatch(h.element('#results').innerHTML,/Post Person|closest Times reporter/);
});
test('Times fallback remains even without topic matches or addresses',()=>{
 const h=harness();h.run(setup+`DATA.people=[{id:'t',name:'Times Person',outlet:'nyt',story_count:5}];`);
 h.element('#q').value='unmatched topic';h.element('#fEmail').checked=true;h.run('runQuery()');
 assert.match(h.element('#results').innerHTML,/Times Person/);assert.match(h.element('#results').innerHTML,/closest Times reporter/);
});
test('name search keeps Times first and finds people with zero clips',()=>{
 const h=harness();h.run(setup+`DATA.people=[{id:'t',name:'Times Person',outlet:'nyt',story_count:5},{id:'j',name:'Jane Example',outlet:'post',story_count:0}];`);
 h.element('#q').value='Jane Example';h.run('runQuery()');const result=h.element('#results').innerHTML;
 assert(result.indexOf('Times Person')<result.indexOf('Jane Example'));assert.match(result,/name match/);assert.doesNotMatch(result,/0 clips on this/);
});
test('core broadcast picks count toward held slots',()=>{
 const h=harness();h.run(`OUT={};DATA={outlets:[]};const ranked=[];
 for(let i=0;i<20;i++){let tv=i<5;let o={id:'o'+i,core:i<2,medium:tv?'tv':'print'};OUT[o.id]=o;DATA.outlets.push(o);ranked.push({p:{id:'p'+i,outlet:o.id},score:tv?10-i:100-i});}ranked.sort((a,b)=>b.score-a.score);const result=shortlist(ranked);`);
 assert.equal(h.run(`result.top.filter(r=>mediumOf(r.p)==='tv').length`),2);assert.equal(h.run('result.top.length'),15);
});
test('one-clip core evidence is displayed; truncated story count is truthful',()=>{
 const h=harness();h.run(setup+`const p={id:'t',name:'Times Person',outlet:'nyt',story_count:80,stories:Array.from({length:12},(_,i)=>({title:'Story '+i,url:'https://example.org/'+i})),beats:[]};`);
 const card=h.run(`card({p,clips:1,why:[{kind:'beat',label:'Housing',count:1,examples:[{title:'Relevant story',url:'https://example.org/relevant'}]}]})`);
 assert.match(card,/Relevant story/);assert.match(card,/show 12 recent stories of 80 harvested/);assert.doesNotMatch(card,/all 80 harvested stories/);
});
test('duplicate addresses and missing addresses are counted separately',()=>{
 const h=harness();h.run(`SELECTED.set('a',{email:'Jane@Example.org'});SELECTED.set('b',{email:'jane@example.org'});SELECTED.set('c',{});updateSelbar();`);
 assert.equal(h.run('selEmails().length'),1);assert.match(h.element('#selnote').textContent,/1 without/);assert.match(h.element('#selnote').textContent,/1 duplicate/);
});
test('select-all reflects partial and full table selection',()=>{
 const h=harness();const rows=[{dataset:{id:'a'}},{dataset:{id:'b'}}];const header={closest:()=>({querySelectorAll:()=>rows})};
 h.lists.set('.selp',rows);h.lists.set('.selall',[header]);h.run(`SELECTED.set('a',{});updateSelbar();`);
 assert.equal(header.indeterminate,true);assert.equal(header.checked,false);
 h.run(`SELECTED.set('b',{});updateSelbar();`);assert.equal(header.indeterminate,false);assert.equal(header.checked,true);
});
console.log(`${passed} UI regression checks passed.`);

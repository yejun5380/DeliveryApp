/* Browser scripts exercised in a small DOM harness. No live Kakao or MySQL. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
    constructor() { this.listeners = {}; this.children = []; this.value = ''; this.disabled = false; this.dataset = {}; }
    addEventListener(name, action) { (this.listeners[name] ||= []).push(action); }
    fire(name, event = {}) { return Promise.all((this.listeners[name] || []).map(action => action(event))); }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); }
    replaceChildren(...children) { this.children = children; }
    querySelectorAll() { return this.children.flatMap(child => child.children || []).filter(child => child instanceof Element); }
    querySelector() { return this.token; }
    style = {};
    set textContent(value) { this.text = value; this.children = []; }
    get textContent() { return this.text || ''; }
}

function harness(script, ids, selectors = {}) {
    const events = new Element();
    const doc = new Element();
    const timeouts = new Map(), intervals = new Map();
    let nextTimer = 1;
    doc.getElementById = id => ids[id];
    doc.querySelectorAll = selector => selectors[selector] || [];
    doc.createElement = () => new Element();
    doc.createTextNode = text => ({text});
    doc.hidden = false;
    const context = {
        document: doc, window: events, AbortController, console,
        setTimeout: (fn, delay) => { const id = nextTimer++; timeouts.set(id, {fn, delay}); return id; },
        clearTimeout: id => timeouts.delete(id),
        setInterval: (fn, delay) => { const id = nextTimer++; intervals.set(id, {fn, delay}); return id; },
        clearInterval: id => intervals.delete(id),
    };
    vm.createContext(context);
    return {context, doc, events, timeouts, intervals,
        run: () => vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static', script), 'utf8'), context)};
}

async function branchPicker() {
    const ids = Object.fromEntries(['branch-picker','search-branches','more-branches','branch-message','branch-list'].map(id => [id, new Element()]));
    ids['branch-picker'].dataset.url = '/restaurant/1/branches';
    const token = new Element(), submit = new Element(), form = new Element();
    form.token = token; submit.disabled = true;
    const h = harness('branches.js', ids, {'.selection-token':[token],'.branch-submit':[submit],'.branch-cart-form':[form]});
    let calls = 0, finish;
    h.context.fetch = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
    h.run();
    assert.equal(calls, 0, 'search must be lazy');
    const pending = ids['search-branches'].fire('click');
    await ids['search-branches'].fire('click');
    assert.equal(calls, 1, 'duplicate clicks share the in-flight UI request');
    finish({ok:true,json:async()=>({places:[{place_id:'1',display_name:'옷데리아 A점',place_name:'롯데리아 A점',road_address:'A 주소',nearby_distance:10,selection_token:'server-token'},
        {place_id:'2',display_name:'옷데리아 B점',place_name:'롯데리아 B점',road_address:'B 주소',nearby_distance:20,selection_token:'other-token'}],is_end:true})});
    await pending;
    assert.equal(ids['branch-list'].children.length, 2);
    await ids['branch-list'].children[1].children[0].fire('change');
    assert.equal(token.value, 'other-token');
    assert.ok(ids['branch-message'].textContent.includes('옷데리아 B점'));
    assert.ok(!ids['branch-message'].textContent.includes('롯데리아'));
    assert.ok(ids['branch-list'].children[0].children[1].text.includes('옷데리아 A점'));
    assert.equal(submit.disabled, false);
    await form.fire('submit', {preventDefault() { throw Error('valid selection should submit'); }});
    assert.equal(submit.disabled, true);
    await h.events.fire('pagehide');
    assert.equal(token.value, '');
    assert.equal(ids['branch-list'].children.length, 0);
    assert.equal(h.timeouts.size, 0);
    const retry = ids['search-branches'].fire('click');
    finish({ok:true,json:async()=>({places:[{place_id:'3',place_name:'롯데리아 원본',road_address:'주소',nearby_distance:10,selection_token:'token'}],is_end:true})});
    await retry;
    assert.ok(!ids['branch-list'].children[0].children[1].text.includes('롯데리아'));
    assert.ok(ids['branch-list'].children[0].children[1].text.includes('가상 음식점 지점'));
}

async function cartCheck() {
    const ids = Object.fromEntries(['check-delivery','order-button','delivery-check-result','order-form','fingerprint'].map(id=>[id,new Element()]));
    const mutation = new Element();
    const h = harness('cart.js', ids, {'form:not(#order-form)':[mutation]});
    let calls=0, finish;
    h.context.fetch=()=>{calls++;return new Promise(resolve=>{finish=resolve;});};
    h.run();
    const pending=ids['check-delivery'].fire('click');
    await ids['check-delivery'].fire('click');
    assert.equal(calls,1);
    finish({ok:true,json:async()=>({status:'available',fingerprint:'checked',limit_meters_label:'10,000m',restaurants:[]})});
    await pending;
    assert.equal(ids['fingerprint'].value,'checked');
    assert.equal(ids['order-button'].disabled,false);
    let prevented=0;
    await ids['order-form'].fire('submit',{preventDefault(){prevented++;}});
    await ids['order-form'].fire('submit',{preventDefault(){prevented++;}});
    assert.equal(prevented,1,'second submit must be blocked');
    await h.events.fire('pageshow');
    assert.equal(ids['fingerprint'].value,'');
    assert.equal(ids['order-button'].disabled,true);
    h.context.fetch=async()=>({ok:true,json:async()=>({status:'unavailable',limit_meters_label:'10,000m',restaurants:[{name:'위치',status:'unavailable',distance:10001}]})});
    await ids['check-delivery'].fire('click');
    assert.ok(ids['delivery-check-result'].children[0].textContent.includes('10,000m 초과'));
    assert.equal(ids['order-button'].disabled,true);
    await mutation.fire('submit');
    assert.equal(ids['fingerprint'].value,'');
    h.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
    const stale=ids['check-delivery'].fire('click');
    await mutation.fire('submit');
    finish({ok:true,json:async()=>({status:'available',fingerprint:'stale',restaurants:[]})});
    await stale;
    assert.equal(ids['fingerprint'].value,'','late response after mutation must be ignored');
}

async function riderLifecycle() {
    const ids = Object.fromEntries(['delivery-data','map','delivery-status','progress','delivery-message'].map(id=>[id,new Element()]));
    ids['delivery-data'].textContent=JSON.stringify({elapsed:0,snapshot:{preparation:600,duration:120,scale:10,
        representative:'가상 지점',path:[{lat:0,lng:0},{lat:0,lng:1},{lat:0,lng:4}]}});
    const h=harness('delivery.js',ids);
    let now=1, overlay, polyline;
    const markerTitles=[];
    h.context.performance={now:()=>now,getEntriesByType:()=>[{responseStart:1}]};
    h.context.kakao={maps:{
        LatLng:class { constructor(lat,lng){this.lat=lat;this.lng=lng;} },
        Map:class {setBounds(){}},
        Polyline:class {constructor(options){polyline=options;}},
        LatLngBounds:class {extend(){}},
        CustomOverlay:class {constructor(options){Object.assign(this,options);overlay=this;}setPosition(position){this.position=position;}setMap(map){this.map=map;}},
        Marker:class {constructor(options){markerTitles.push(options.title);}},
    }};
    h.run();
    assert.equal(markerTitles[0],'가상 지점');
    assert.equal(h.intervals.size,1);
    assert.equal([...h.intervals.values()][0].delay,100);
    await h.events.fire('pageshow');
    assert.equal(h.intervals.size,1,'pageshow must not duplicate the timer');
    h.doc.hidden=true; await h.doc.fire('visibilitychange');
    assert.equal(h.intervals.size,0);
    now=66001; h.doc.hidden=false; await h.doc.fire('visibilitychange');
    assert.equal(h.intervals.size,1);
    assert.ok(Math.abs(overlay.position.lng-2)<1e-9,'resume uses elapsed time and cumulative road length');
    assert.equal(polyline.path.length,3);
    now=72001; [...h.intervals.values()][0].fn();
    assert.equal(h.intervals.size,0,'completion clears timer');
    assert.equal(overlay.position.lng,4);
    assert.equal(ids.progress.value,1);
    await h.events.fire('pagehide');
    assert.equal(h.intervals.size,0);
}

(async()=>{
    await branchPicker(); await cartCheck(); await riderLifecycle();
    console.log('PASS: lazy branch selection, request deduplication, cart invalidation, double submission, 10km labels, rider 100ms timer and resume/completion');
})().catch(error=>{console.error(error);process.exitCode=1;});

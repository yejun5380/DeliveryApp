const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {sliceAt,tooltipPosition}=require('../static/chart_details.js');
const items=[{name:'메뉴 A',calories:1000,percent:'25.0',start:'0',end:'25'},
             {name:'메뉴 B',calories:3000,percent:'75.0',start:'25',end:'100'}];
const rect={left:10,top:100,width:200,height:200};
assert.equal(sliceAt(items,rect,110,100).name,'메뉴 A');
assert.equal(sliceAt(items,rect,210,200).name,'메뉴 B');
assert.equal(sliceAt(items,rect,110,200),null,'the donut hole is not a segment');
assert.equal(sliceAt(items,rect,500,200),null);
for(const [x,y] of [[374,811],[0,0],[900,1200]]) {
    const p=tooltipPosition(x,y,300,90,375,812);
    assert.ok(p.left>=8&&p.left+300<=367&&p.top>=8&&p.top+90<=804);
}
class Element {
    constructor(rectangle=rect){this.rect=rectangle;this.events={};this.dataset={};this.style={};this.attributes={};this.hidden=false;}
    addEventListener(name,fn){(this.events[name]||=[]).push(fn);}
    fire(name,event={}){for(const fn of this.events[name]||[])fn(event);}
    getBoundingClientRect(){return this.rect;}
    setAttribute(name,value){this.attributes[name]=value;}
    removeAttribute(name){delete this.attributes[name];}
    contains(target){return target===this;}
    set innerHTML(_){throw Error('Tooltip content must be text, never HTML');}
}
const tooltip=new Element({width:300,height:90});tooltip.hidden=true;
const bar=new Element();bar.dataset.chartTooltip='2026-01-05 · 20,000원';
const donut=new Element();donut.dataset.calorieSource='calorie-data-daily';
const button=new Element(),doc=new Element(),win=new Element();win.innerWidth=375;win.innerHeight=812;
doc.getElementById=id=>id==='chart-tooltip'?tooltip:{textContent:JSON.stringify(items)};
doc.querySelectorAll=selector=>({'[data-chart-tooltip]':[bar],'[data-calorie-source]':[donut],'.saving-periods button':[button]})[selector]||[];
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/chart_details.js'),'utf8'),{document:doc,window:win});
bar.fire('pointermove',{pointerType:'mouse',clientX:374,clientY:811});
assert.equal(tooltip.hidden,false);assert.equal(tooltip.textContent,'2026-01-05 · 20,000원');
bar.fire('pointerleave',{pointerType:'mouse'});assert.equal(tooltip.hidden,true);
bar.fire('click');bar.fire('pointerleave',{pointerType:'touch'});assert.equal(tooltip.hidden,false);
doc.fire('pointerdown',{target:button});assert.equal(tooltip.hidden,true);
donut.fire('pointermove',{pointerType:'mouse',clientX:210,clientY:200});
assert.equal(tooltip.textContent,'메뉴 B · 3,000 kcal · 75.0%');
donut.fire('click',{clientX:110,clientY:100});
donut.fire('pointerleave',{pointerType:'touch'});assert.equal(tooltip.hidden,false);
assert.equal(tooltip.textContent,'메뉴 A · 1,000 kcal · 25.0%');
donut.fire('keydown',{key:'ArrowRight',preventDefault(){}});assert.ok(tooltip.textContent.startsWith('메뉴 B'));
doc.fire('keydown',{key:'Escape'});assert.equal(tooltip.hidden,true);
bar.fire('focus');button.fire('click');assert.equal(tooltip.hidden,true);
console.log('PASS: mouse hover, touch persistence, keyboard, period dismissal, slice hit testing and viewport-safe tooltips');

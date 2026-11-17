/* Dependency-free hit testing and viewport-safe chart details. */
(function (root) {
    function sliceAt(items, rect, x, y) {
        const dx=x-(rect.left+rect.width/2), dy=y-(rect.top+rect.height/2);
        const radius=Math.min(rect.width,rect.height)/2, distance=Math.hypot(dx,dy);
        if(distance<radius*.66 || distance>radius) return null;
        const percent=((Math.atan2(dy,dx)*180/Math.PI+450)%360)/3.6;
        return items.find(item=>percent>=Number(item.start)&&percent<Number(item.end)) || null;
    }
    function tooltipPosition(x,y,width,height,viewportWidth,viewportHeight) {
        return {left:Math.max(8,Math.min(x+12,viewportWidth-width-8)),
                top:Math.max(8,Math.min(y+12,viewportHeight-height-8))};
    }
    const api={sliceAt,tooltipPosition};
    if(typeof module!=='undefined') module.exports=api;
    root.ChartDetails=api;
    if(typeof document==='undefined') return;
    const tooltip=document.getElementById('chart-tooltip');
    if(!tooltip) return;
    let active=null, pinned=false;
    function hide() {
        tooltip.hidden=true;
        active?.removeAttribute('aria-describedby');
        active=null; pinned=false;
    }
    function show(target,text,x,y,pin=false) {
        if(active && active!==target) active.removeAttribute('aria-describedby');
        active=target; pinned=pin;
        tooltip.textContent=text; tooltip.hidden=false;
        target.setAttribute('aria-describedby','chart-tooltip');
        const size=tooltip.getBoundingClientRect();
        const position=tooltipPosition(x,y,size.width,size.height,window.innerWidth,window.innerHeight);
        tooltip.style.left=`${position.left}px`;tooltip.style.top=`${position.top}px`;
    }
    function anchor(target) {
        const rect=target.getBoundingClientRect();return {x:rect.left+rect.width/2,y:rect.top};
    }
    document.querySelectorAll('[data-chart-tooltip]').forEach(target=>{
        target.addEventListener('pointermove',event=>{
            if(event.pointerType!=='touch'&&!pinned) show(target,target.dataset.chartTooltip,event.clientX,event.clientY);
        });
        target.addEventListener('pointerleave',event=>{if(event.pointerType!=='touch'&&!pinned) hide();});
        target.addEventListener('focus',()=>{const p=anchor(target);show(target,target.dataset.chartTooltip,p.x,p.y);});
        target.addEventListener('blur',hide);
        target.addEventListener('click',()=>{const p=anchor(target);show(target,target.dataset.chartTooltip,p.x,p.y,true);});
        target.addEventListener('keydown',event=>{
            if(event.key==='Enter'||event.key===' ') {event.preventDefault();const p=anchor(target);show(target,target.dataset.chartTooltip,p.x,p.y,true);}
        });
    });
    document.querySelectorAll('[data-calorie-source]').forEach(target=>{
        const items=JSON.parse(document.getElementById(target.dataset.calorieSource).textContent);
        let selected=0;
        function describe(item,x,y,pin=false) {
            if(!item) {if(!pinned) hide();return;}
            selected=items.indexOf(item);
            show(target,`${item.name} · ${Number(item.calories).toLocaleString('ko-KR')} kcal · ${item.percent}%`,x,y,pin);
        }
        target.addEventListener('pointermove',event=>{
            if(event.pointerType!=='touch'&&!pinned) describe(sliceAt(items,target.getBoundingClientRect(),event.clientX,event.clientY),event.clientX,event.clientY);
        });
        target.addEventListener('pointerleave',event=>{if(event.pointerType!=='touch'&&!pinned) hide();});
        target.addEventListener('click',event=>{
            const item=sliceAt(items,target.getBoundingClientRect(),event.clientX,event.clientY);
            if(item) describe(item,event.clientX,event.clientY,true);else hide();
        });
        target.addEventListener('focus',()=>{const p=anchor(target);describe(items[selected],p.x,p.y);});
        target.addEventListener('blur',hide);
        target.addEventListener('keydown',event=>{
            if(['ArrowRight','ArrowLeft','Enter',' '].includes(event.key)) {
                event.preventDefault();
                if(event.key==='ArrowRight') selected=(selected+1)%items.length;
                if(event.key==='ArrowLeft') selected=(selected+items.length-1)%items.length;
                const p=anchor(target);describe(items[selected],p.x,p.y,true);
            }
        });
    });
    document.addEventListener('pointerdown',event=>{if(active&&!active.contains(event.target)) hide();});
    document.addEventListener('keydown',event=>{if(event.key==='Escape') hide();});
    document.querySelectorAll('.saving-periods button').forEach(button=>button.addEventListener('click',hide));
    window.addEventListener('resize',hide);
    document.addEventListener('scroll',hide,true);
})(globalThis);

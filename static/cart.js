(() => {
    const check=document.getElementById('check-delivery');
    if(!check) return;
    const order=document.getElementById('order-button'), result=document.getElementById('delivery-check-result'), form=document.getElementById('order-form'), fingerprint=document.getElementById('fingerprint');
    let busy=false, submitting=false, controller=null, expiry=null, generation=0;
    function invalidate() {generation++;order.disabled=true;fingerprint.value='';if(expiry) clearTimeout(expiry);}
    check.addEventListener('click',async()=>{
        if(busy||submitting) return;
        busy=true;check.disabled=true;invalidate();result.textContent='실제 도로 거리 확인 중...';
        const currentGeneration=generation;
        controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),90000);
        try {
            const response=await fetch('/cart/delivery-check',{method:'POST',signal:controller.signal,cache:'no-store'});
            const data=await response.json();
            if(currentGeneration!==generation) return;
            result.textContent=data.message || ({available:'모든 음식점 배달 가능',unavailable:'배달 범위 초과 음식점이 있습니다.',unknown:'배달 가능 여부 확인 불가'})[data.status];
            for(const row of data.restaurants||[]) {
                const line=document.createElement('p');
                line.textContent=`${row.name}: ${row.distance!=null?`${(row.distance/1000).toFixed(2)}km (${row.distance}m) / `:''}${({available:'배달 가능',unavailable:`${data.limit_meters_label} 초과, 배달 불가`,unknown:'확인 불가'})[row.status]} ${row.message||''}`;
                result.appendChild(line);
            }
            if(response.ok&&data.status==='available') {fingerprint.value=data.fingerprint;order.disabled=false;expiry=setTimeout(()=>{invalidate();result.textContent='검사 결과가 만료되었습니다. 다시 확인해 주세요.';},60000);}
        } catch {if(currentGeneration===generation) result.textContent='배달 가능 여부를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.';}
        finally {clearTimeout(timeout);busy=false;check.disabled=false;controller=null;}
    });
    form.addEventListener('submit',event=>{if(busy||submitting||!fingerprint.value){event.preventDefault();return;}submitting=true;order.disabled=true;check.disabled=true;});
    document.querySelectorAll('form:not(#order-form)').forEach(f=>f.addEventListener('submit',()=>{invalidate();controller?.abort();}));
    window.addEventListener('pagehide',()=>{controller?.abort();invalidate();});
    window.addEventListener('pageshow',()=>{invalidate();submitting=false;check.disabled=false;result.textContent='주소·장바구니 변경 여부를 반영하려면 다시 확인해 주세요.';});
    window.addEventListener('focus',()=>{if(!submitting){invalidate();controller?.abort();result.textContent='최신 배달 가능 여부를 다시 확인해 주세요.';}});
    document.addEventListener('visibilitychange',()=>{if(document.hidden&&!submitting){invalidate();controller?.abort();}});
})();

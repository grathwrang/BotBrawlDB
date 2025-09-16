
document.addEventListener('DOMContentLoaded', () => {
  const hook = (root) => {
    const file = root.querySelector('input[type=file]');
    const previewBox = root.querySelector('.preview');
    if (!file || !previewBox) return;

    file.addEventListener('change', () => {
      const f = file.files && file.files[0];
      if (!f) { previewBox.innerHTML = '<span>Drag & Drop image here<br><span class="small">(or click to select)</span></span>'; return; }
      const url = URL.createObjectURL(f);
      previewBox.innerHTML = '';
      const img = document.createElement('img');
      img.src = url;
      img.alt = 'preview';
      previewBox.appendChild(img);
    });
  };
  document.querySelectorAll('.dropzone').forEach(hook);
});


function attachRobotRowHandlers(){
  const modal = document.getElementById('robotModal');
  const modalContent = document.getElementById('robotModalContent');
  if (!modal || !modalContent) return;
  document.querySelectorAll('tr.robot-row').forEach(tr => {
    tr.addEventListener('dblclick', () => {
      const wc = tr.dataset.wc;
      const name = tr.dataset.name;
      fetch(`/robot_card2/${encodeURIComponent(wc)}/${encodeURIComponent(name)}`)
        .then(r => { if(!r.ok) throw new Error(`Not found (${r.status})`); return r.text(); })
        .then(html => { modalContent.innerHTML = html; modal.showModal(); })
        .catch(err => { modalContent.innerHTML = `<h3 style='color:#e53935;margin:0 0 8px'>Could not load robot card</h3><p class='small'>${name} in ${wc}</p><p class='small'>${err}</p>`; modal.showModal(); });
    });
  });
}
document.addEventListener('DOMContentLoaded', attachRobotRowHandlers);


function attachPublicScheduleHandlers(){
  const modal = document.getElementById('robotModal');
  const modalContent = document.getElementById('robotModalContent');
  if (!modal || !modalContent) return;
  document.querySelectorAll('.robot-link').forEach(el => {
    el.addEventListener('click', () => {
      const wc = el.dataset.wc;
      const name = el.dataset.name;
      fetch(`/robot_card2/${encodeURIComponent(wc)}/${encodeURIComponent(name)}`)
        .then(r => { if(!r.ok) throw new Error(`Not found (${r.status})`); return r.text(); })
        .then(html => { modalContent.innerHTML = html; modal.showModal(); })
        .catch(err => { modalContent.innerHTML = `<h3 style='color:#e53935;margin:0 0 8px'>Could not load robot card</h3><p class='small'>${name} in ${wc}</p><p class='small'>${err}</p>`; modal.showModal(); });
    });
  });
}
document.addEventListener('DOMContentLoaded', attachPublicScheduleHandlers);


document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.robot-link').forEach(el => {
    el.setAttribute('role','button');
    el.setAttribute('tabindex','0');
    el.addEventListener('keyup', (e) => {
      if (e.key === 'Enter' || e.key === ' ') el.click();
    });
  });
});

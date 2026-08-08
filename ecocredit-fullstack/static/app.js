const $ = (selector) => document.querySelector(selector);
let selectedCategory = 'All';

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('visible');
  setTimeout(() => element.classList.remove('visible'), 3500);
}

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Something went wrong.');
  return data;
}

function itemCard(item) {
  return `<article class="item-card"><div class="item-visual">${item.emoji}</div><div class="item-body"><span class="item-meta">${item.category.toUpperCase()} · ${item.item_condition.toUpperCase()}</span><h3>${item.title}</h3><p>${item.location} · Listed by ${item.owner_name}</p><div class="item-bottom"><span>✦ ${item.points} points</span><button class="request" data-request="${item.id}">Request</button></div></div></article>`;
}

async function loadItems() {
  const items = await api(`/api/items?category=${encodeURIComponent(selectedCategory)}`);
  $('#items').innerHTML = items.length ? items.map(itemCard).join('') : '<p class="empty">No items here yet. Why not list the first one?</p>';
  document.querySelectorAll('[data-request]').forEach(button => button.addEventListener('click', () => requestItem(button.dataset.request)));
}

async function loadStats() {
  const stats = await api('/api/stats');
  $('#wasteStat').textContent = `${stats.waste_prevented} kg`;
  $('#itemsStat').textContent = stats.items_reused.toLocaleString();
  $('#savingStat').textContent = stats.student_savings;
  $('#requestStat').textContent = stats.requests;
}

async function requestItem(id) {
  try { const data = await api(`/api/items/${id}/request`, { method: 'POST' }); toast(data.message); loadStats(); }
  catch (error) { toast(error.message); }
}

function openModal() { $('#itemModal').showModal(); }
function closeModal() { $('#itemModal').close(); $('#formMessage').textContent = ''; }

$('#loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('#loginError').style.display = 'none';
  try {
    const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ email: $('#email').value, password: $('#password').value }) });
    startApp(data.user);
  } catch (error) { $('#loginError').textContent = error.message; $('#loginError').style.display = 'block'; }
});

$('#itemForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const data = await api('/api/items', { method: 'POST', body: JSON.stringify({ title: $('#itemTitle').value, category: $('#itemCategory').value, condition: $('#itemCondition').value, location: $('#itemLocation').value, points: $('#itemPoints').value }) });
    $('#formMessage').textContent = data.message;
    $('#itemForm').reset();
    loadItems(); api('/api/me').then(data => { $('#points').textContent = data.user.eco_points; });
  } catch (error) { $('#formMessage').textContent = error.message; }
});

$('#openList').addEventListener('click', openModal); $('#heroList').addEventListener('click', openModal); $('#closeModal').addEventListener('click', closeModal);
$('#logout').addEventListener('click', async () => { await api('/api/auth/logout', { method: 'POST' }); $('#app').hidden = true; $('#loginPage').hidden = false; });
$('#filters').addEventListener('click', (event) => { if (!event.target.dataset.category) return; selectedCategory = event.target.dataset.category; document.querySelectorAll('#filters button').forEach(button => button.classList.toggle('active', button === event.target)); loadItems(); });

function startApp(user) { $('#loginPage').hidden = true; $('#app').hidden = false; $('#welcome').textContent = `Hi, ${user.name.split(' ')[0]}`; $('#points').textContent = user.eco_points; loadItems(); loadStats(); }

api('/api/me').then(data => { if (data.logged_in) startApp(data.user); });

let qtyModalCallback = null;
function showQtyModal(title, min, max, callback) {
    const modal = document.getElementById('qtyModal');
    document.getElementById('qtyModalTitle').textContent = title;
    const input = document.getElementById('qtyInput');
    input.min = min;
    input.max = max;
    input.value = min;
    qtyModalCallback = callback;
    modal.classList.remove('hidden');
    input.focus();
}
function hideQtyModal() {
    document.getElementById('qtyModal').classList.add('hidden');
    qtyModalCallback = null;
}
document.getElementById('qtyConfirm').onclick = () => {
    const input = document.getElementById('qtyInput');
    let val = parseInt(input.value);
    if (isNaN(val) || val < parseInt(input.min) || val > parseInt(input.max)) {
        input.focus();
        return;
    }
    if (qtyModalCallback) qtyModalCallback(val);
    hideQtyModal();
};
document.getElementById('qtyCancel').onclick = hideQtyModal;

function getUser() {
    const u = localStorage.getItem('user');
    return u ? JSON.parse(u) : null;
}

function q(id) {
    return document.getElementById(id);
}

function setWelcome(user) {
    const wel = document.getElementById('welcome');
    if (user) {
        wel.textContent = `Hola ${user.user_name}`;
        document.getElementById('logoutBtn').classList.remove('hidden');
        document.getElementById('showLogin').classList.add('hidden');
        document.getElementById('showRegister').classList.add('hidden');
    } else {
        wel.textContent = '';
        document.getElementById('logoutBtn').classList.add('hidden');
        document.getElementById('showLogin').classList.remove('hidden');
        document.getElementById('showRegister').classList.remove('hidden');
    }
}

function toggleSection(id) {
    document.querySelectorAll('section').forEach(sec => sec.classList.add('hidden'));
    if (id) {
        document.getElementById(id).classList.remove('hidden');
    }
}

function detectCardOperator(number) {
    if (!number) return null;
    number = number.replace(/\D/g, ''); 
    if (/^4/.test(number)) return 'Visa';
    if (/^(5[1-5]|2[2-7])/.test(number)) return 'Mastercard';
    if (/^3[47]/.test(number)) return 'American Express';
    if (/^50|^(5[6-9])|^(6[0-9])/.test(number)) return 'Cabal';
    if (/^6042/.test(number)) return 'Cabal';
    return null;
}

document.getElementById('cardNumber').addEventListener('input', function (e) {
    const operator = detectCardOperator(e.target.value);
    const logo = document.getElementById('bankLogo');
    if (operator) {
        logo.style.display = 'inline';
        if (operator === 'Visa') logo.src = '/static/img/visa.png';
        else if (operator === 'Mastercard') logo.src = '/static/img/Mastercard.png';
        else if (operator === 'American Express') logo.src = '/static/img/american.png';
        else if (operator === 'Cabal') logo.src = '/static/img/cabal.jpeg';
        else logo.style.display = 'none';
    } else {
        logo.style.display = 'none';
    }
});


async function loadProducts() {
    try {
        const res = await fetch('/productos');
        if (res.ok) {
            const data = await res.json();
            const container = document.getElementById('productList');
            container.innerHTML = '';
            if (!data.length) {
                container.innerHTML = '<p>No hay productos disponibles</p>';
                return;
            }
            data.forEach(p => {
                const precioFinal = p.precio_con_descuento !== undefined ? p.precio_con_descuento : (p.price * (1 - (p.descuento || 0)/100));
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = `
                    <img src="${p.image || 'https://via.placeholder.com/200x120'}" alt="img">
                    <h3>${p.name}</h3>
                    <p style="font-size:0.98em;color:#e0e0e0;min-height:38px;margin-bottom:2px;">${p.description ? p.description : ''}</p>
                    <p>
                        <span ${p.descuento ? 'style="text-decoration:line-through;color:gray"' : ''}>$${p.price}</span>
                        ${p.descuento ? `<b style="margin-left:7px;color:#17e4bd">$${precioFinal}</b> <span style="font-size:.9em;color:#bbb">(-${p.descuento}%)</span>` : ''}
                    </p>
                    <p>Stock: <b>${p.stock ?? 0}</b></p>
                `;
                const btn = document.createElement('button');
                btn.textContent = 'Agregar';
                btn.onclick = () => {
                    showQtyModal(
                        `¿Cuántos '${p.name}' agregar? (Stock: ${p.stock ?? 0})`,
                        1, p.stock ?? 1,
                        amount => addToCart(p.idProducto, amount)
                    );
                };
                card.appendChild(btn);
                container.appendChild(card);
            });
        }
    } catch (err) {
        console.error(err);
        alert('Error al cargar productos');
    }
}


async function addToCart(prodId, amount) {
    const user = getUser();
    if (!user) return alert('Debe iniciar sesión');
    const payload = { product_id: prodId, amount };
    try {
        const res = await fetch(`/carrito/agregar/user_id/${user.idUser}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            await loadCart();
            alert('Producto agregado');
        } else {
            alert('Error al agregar al carrito');
        }
    } catch {
        alert('Error de conexión');
    }
}

async function loadCart() {
    const user = getUser();
    if (!user) return;
    try {
        const res = await fetch(`/carrito/user_id/${user.idUser}`);
        if (res.ok) {
            const data = await res.json();
            const list = document.getElementById('cartList');
            list.innerHTML = '';
            data.forEach(it => {
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = `
                    ${it.image ? `<img src="${it.image}" alt="${it.name}" style="width:100%;height:90px;object-fit:cover;border-radius:7px;margin-bottom:0.5rem;">` : ''}
                    <h3 style="font-size:1.1rem;">${it.name}</h3>
                    <p>Cantidad: ${it.amount}</p>
                `;
                const btnAdd = document.createElement('button');
                btnAdd.textContent = 'Agregar';
                btnAdd.onclick = () => {
                    showQtyModal(
                        `¿Cuántos agregar?`,
                        1, 99,
                        amount => addToCart(it.product_id, amount)
                    );
                };
                const btnDel = document.createElement('button');
                btnDel.textContent = 'Quitar';
                btnDel.onclick = () => {
                    showQtyModal(
                        `¿Cuántos eliminar? (En carrito: ${it.amount})`,
                        1, it.amount,
                        amount => removeFromCart(it.product_id, amount)
                    );
                };
                card.appendChild(btnAdd);
                card.appendChild(btnDel);
                list.appendChild(card);
            });
        }
    } catch {}
}

async function removeFromCart(prodId, amount) {
    const user = getUser();
    if (!user) return;
    const payload = { product_id: prodId, amount };
    await fetch(`/carrito/borrar/user_id/${user.idUser}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    loadCart();
}



async function confirmCart() {
    const user = getUser();
    if (!user) return;
    const res = await fetch(`/carrito/confirmar/user_id/${user.idUser}`, { method: 'POST' });
    if (res.ok) {
        const info = await res.json();
        document.getElementById('orderInfo').textContent = `Venta ${info.idVenta} - Total $${info.TotalDeVenta} (IVA ${info.IVA}%)`;
        document.getElementById('orderSection').dataset.venta = info.idVenta;
        toggleSection('orderSection');
    } else {
        alert('No se pudo confirmar');
    }
}

async function getPendingOrder() {
    const user = getUser();
    if (!user) return;
    const res = await fetch(`/carrito/pedido/user_id/${user.idUser}`);
    if (res.ok) {
        const info = await res.json();
        document.getElementById('orderInfo').textContent = `Venta ${info.idVenta} - Total $${info.TotalDeVenta} (IVA ${info.IVA}%)`;
        document.getElementById('orderSection').dataset.venta = info.idVenta;
        toggleSection('orderSection');
    }
}

async function deleteOrder() {
    const user = getUser();
    if (!user) return;
    await fetch(`/carrito/pedido/user_id/${user.idUser}`, { method: 'DELETE' });
    toggleSection('productSection');
    loadCart();
}


async function payOrder(e) {
    e.preventDefault();
    const user = getUser();
    if (!user) return;
    const venta = Number(document.getElementById('orderSection').dataset.venta);
    const method = document.getElementById('payMethod').value;
    const payload = { metodo: method };
    if (method === 'Tarjeta') {
        const numero = document.getElementById('cardNumber').value.trim();
        const operator = detectCardOperator(numero);
        if (!operator) {
            alert('Número de tarjeta no válido. Solo se acepta Visa, Mastercard, American Express o Cabal.');
            return;
        }
        payload.numero_tarjeta = numero;
        payload.nombre_tarjeta = document.getElementById('cardName').value;
        payload.fecha_vencimiento = document.getElementById('cardExp').value;
        payload.ccv = document.getElementById('cardCCV').value;
        payload.guardar_tarjeta = document.getElementById('saveCard').checked;
    }
    const res = await fetch(`/ventas/comprar/${user.idUser}/${venta}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (res.ok) {
        alert('Compra realizada');
        toggleSection('productSection');
        loadCart();
        loadSales();
        loadProducts();
    } else {
        alert('Error al realizar pago');
    }
}



async function loadSales() {
    const user = getUser();
    if (!user) return;

    const res = await fetch(`/ventas/historial/${user.idUser}`);
    if (!res.ok) return;

    const data = await res.json();
    const list = document.getElementById('salesList');
    list.innerHTML = '';

    data.forEach(v => {
        const productosHtml = v.productos.map(p => `
            <li>
                ${p.nombre} (x${p.cantidad})<br>
                Precio unitario: 
                <span ${p.descuento ? 'style="text-decoration:line-through;color:gray"' : ''}>
                    $${p.precio_original.toFixed(2)}
                </span>
                ${p.descuento
                    ? `<b style="margin-left:7px;color:#17e4bd">
                         $${p.precio_unitario.toFixed(2)}
                       </b> 
                       <span style="font-size:.9em;color:#bbb">
                         (-${p.descuento}%)
                       </span>`
                    : ''}
                <br>
                Subtotal: $${p.subtotal.toFixed(2)}
            </li>
        `).join('');
        const fecha     = v.fecha      ? new Date(v.fecha).toLocaleString('es-AR')     : '-';
        const fechaPago = v.fecha_pago ? new Date(v.fecha_pago).toLocaleString('es-AR') : '-';
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
            <h3>Venta ${v.idVenta}</h3>
            <p><b>Usuario:</b> ${v.nombre} (${v.user_name})</p>
            <p><b>Fecha venta:</b> ${fecha}</p>
            <ul>${productosHtml}</ul>
            <p>
              <b>Total a pagar:</b> 
              $${Number(v.total).toFixed(2)} 
              <small>(IVA ${v.IVA}%)</small>
            </p>
            <p><b>Método de pago:</b> ${v.metodo_pago || '-'}</p>
            <p><b>Operador:</b> ${v.operador     || '-'}</p>
            <p><b>Fecha de pago:</b> ${fechaPago}</p>
        `;
        list.appendChild(card);
    });
}




async function checkHealth() {
    const res = await fetch('/health');
    if (res.ok) {
        const data = await res.json();
        document.getElementById('healthStatus').textContent = JSON.stringify(data, null, 2);
    }
}

function showProfile() {
    const user = getUser();
    if (!user) return;
    q('profileInfo').innerHTML = `
        <p>Usuario: ${user.user_name}</p>
        <p>Nombre: ${user.name} ${user.last_name || ''}</p>
        <p>DNI: ${user.dni || ''}</p>
        <p>Dirección: ${user.address || ''}</p>
        <p>IVA: ${user.iva_condition || ''}</p>
    `;
}

async function loadCards() {
    const user = getUser();
    if (!user) return;
    const res = await fetch(`/usuario/tarjetas/user_id/${user.idUser}`);
    const list = q('cardList');
    list.innerHTML = '';
    if (res.ok) {
        const data = await res.json();
        (data.TarjetasGuardadas || []).forEach(card => {
            if (typeof card === 'string') {
                let ult4 = card.slice(-4);
                list.innerHTML += `<li>**** **** **** ${ult4}</li>`;
            } else {
                const operador = card.operador ? `<b>${card.operador}</b> ` : '';
                list.innerHTML += `<li>${operador} | **** **** **** ${card.ultimos4} | ${card.nombre} | ${card.fecha_vencimiento}</li>`;
            }
        });
    } else {
        alert('No se encontraron tarjetas');
    }
}


async function addProduct(e) {
    e.preventDefault();
    const user = getUser();
    if (!user) return alert('Debe iniciar sesión');
    const payload = {
        name: q('prodName').value,
        description: q('prodDesc').value,
        price: parseFloat(q('prodPrice').value),
        stock: parseInt(q('prodStock').value || '0'),
        descuento: parseInt(q('prodDiscount').value || '0'),
        image: q('prodImage').value
    };
    const res = await fetch(`/productos/user_id/${user.idUser}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (res.ok) {
        alert('Producto agregado');
        e.target.reset();
        loadProducts();
    } else {
        alert('Error al agregar producto');
    }
}


async function updateProduct(e) {
    e.preventDefault();
    const user = getUser();
    if (!user) return;
    const name = q('updName').value;
    const payload = {};
    if (q('updNewName').value) payload.name = q('updNewName').value;
    if (q('updDesc').value) payload.description = q('updDesc').value;
    if (q('updPrice').value) payload.price = parseFloat(q('updPrice').value);
    if (q('updStock').value) payload.stock = parseInt(q('updStock').value);
    if (q('updDiscount').value) payload.descuento = parseInt(q('updDiscount').value);
    if (q('updImage').value) payload.image = q('updImage').value;
    const res = await fetch(`/productos/name/${encodeURIComponent(name)}/user_id/${user.idUser}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (res.ok) {
        alert('Producto actualizado');
        e.target.reset();
        loadProducts();
    } else {
        alert('Error al actualizar');
    }
}

async function deleteProduct(e) {
    e.preventDefault();
    const user = getUser();
    if (!user) return;
    const name = q('delName').value;
    const res = await fetch(`/productos/name/${encodeURIComponent(name)}/user_id/${user.idUser}`, {
        method: 'DELETE'
    });
    if (res.ok) {
        alert('Producto eliminado');
        e.target.reset();
        loadProducts();
    } else {
        alert('Error al eliminar');
    }
}


async function loadHistory(e) {
  e.preventDefault();
  const nombre = document.getElementById('histProdName').value.trim();
  if (!nombre) return alert('Debe ingresar un nombre de producto.');

  const res = await fetch(`/productos/activity/${encodeURIComponent(nombre)}`);
  const list = document.getElementById('historyList');
  list.innerHTML = '';

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg = err.detail || 'Error al consultar historial';
    list.innerHTML = `<p class="history-error">${msg}</p>`;
    return;
  }

  const { logs } = await res.json();
  if (!logs.length) {
    list.innerHTML = `<p class="history-no-data">No hay historial de cambios para “${nombre}”.</p>`;
    return;
  }

  logs.forEach(l => {
    const fecha = new Date(l.event_time).toLocaleString('es-AR');
    let bodyHtml = '';

    if (l.event_type === 'ADD_PRODUCT') {
      const prod = JSON.parse(l.producto);
      bodyHtml = `
        <ul class="history-details">
          <li><strong>ID:</strong> ${l.product_id}</li>
          <li><strong>Nombre:</strong> ${prod.name}</li>
          <li><strong>Descripción:</strong> ${prod.description || '-'}</li>
          <li><strong>Precio:</strong> $${prod.price.toFixed(2)}</li>
          <li><strong>Stock:</strong> ${prod.stock}</li>
          <li><strong>Descuento:</strong> ${prod.descuento || 0}%</li>
          <li><strong>Imagen:</strong> 
            ${prod.image 
              ? `<a href="${prod.image}" target="_blank">Ver imagen</a>` 
              : '-'
            }
          </li>
          <li><strong>Fecha alta:</strong> ${new Date(prod.date_added).toLocaleString('es-AR')}</li>
        </ul>`;
    } else {
      bodyHtml = `
        <p><strong>Campo modificado:</strong> ${l.field}</p>
        <p><strong>Valor anterior:</strong> ${l.old_value ?? '-'}</p>
        <p><strong>Nuevo valor:</strong> ${l.new_value ?? '-'}</p>`;
    }

    const card = document.createElement('div');
    card.className = 'history-card';
    card.innerHTML = `
      <div class="history-card-header">
        ${l.event_type.replace(/_/g,' ')}
      </div>
      <div class="history-card-meta">
        ${fecha} &bull; Operador: ${l.user_id}
      </div>
      <div class="history-card-body">
        ${bodyHtml}
      </div>`;

    list.appendChild(card);
  });
}



async function loadCartHistory() {
    const user = getUser();
    if (!user) return;
    const res = await fetch(`/carrito/historial/user_id/${user.idUser}`);
    const list = q('cartHistoryList');
    list.innerHTML = '';
    q('cartHistory').classList.remove('hidden');
    if (res.ok) {
        const data = await res.json();
        if (data.length === 0) {
            list.innerHTML = '<li>No hay historial disponible</li>';
            return;
        }
        data.forEach(log => {
            const fecha = new Date(log.fecha).toLocaleString('es-AR');
            const li = document.createElement('li');
            li.style.marginBottom = '1rem';
            li.style.display = 'flex';
            li.style.alignItems = 'center';

            let desc = `<span style="font-weight:bold;color:#14ffd5;">${fecha}</span> &nbsp; `;
            desc += `<span style="color:white">${log.descripcion}</span>`;
            if (log.producto) {
                desc += ` <span style="color:#fbbd1f; font-weight:bold;">${log.producto}</span>`;
            }
            li.innerHTML = `<div style="display:flex;align-items:center;gap:12px;">${desc}</div>`;

            const btn = document.createElement('button');
            btn.textContent = '⟲ Restaurar';
            btn.onclick = () => restoreCart(log.fecha);
            btn.style.background = 'linear-gradient(90deg,#15dfb3 60%,#02ff81 100%)';
            btn.style.color = '#222';
            btn.style.border = 'none';
            btn.style.padding = '5px 13px';
            btn.style.borderRadius = '1rem';
            btn.style.fontWeight = 'bold';
            btn.style.cursor = 'pointer';
            btn.style.boxShadow = '0 2px 7px #2225';
            btn.style.marginLeft = '16px';
            li.appendChild(btn);

            list.appendChild(li);
        });
    } else {
        list.innerHTML = '<li>Error al cargar historial</li>';
    }
}


async function restoreCart(eventTime) {
    const user = getUser();
    if (!user) return;
    const res = await fetch(`/carrito/restaurar/user_id/${user.idUser}?event_time=${encodeURIComponent(eventTime)}`, {
        method: 'POST'
    });
    if (res.ok) {
        await loadCart();
        alert('Carrito restaurado');
    } else {
        alert('No se pudo restaurar');
    }
}

async function loadPrices() {
    const res = await fetch('/productos/precios');
    const list = q('priceList');
    list.innerHTML = '';
    if (res.ok) {
        const data = await res.json();
        data.forEach(p => {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `<h3>${p.name}</h3><p>$${p.price}</p><p>Descuento: ${p.descuento}%</p>`;
            list.appendChild(card);
        });
    } else {
        list.innerHTML = '<p>Error al cargar precios</p>';
    }
}

async function loadPayments() {
    const user = getUser();
    if (!user) return;
    const res = await fetch(`/ventas/historial_pagos/${user.idUser}`);
    if (res.ok) {
        const data = await res.json();
        const list = document.getElementById('paymentsList');
        list.innerHTML = '';
        if (!data.length) {
            list.innerHTML = '<p>No hay pagos registrados.</p>';
            return;
        }
        data.forEach(pago => {
            const fecha = pago.fecha ? new Date(pago.fecha).toLocaleString('es-AR') : '';
            const ventas = pago.ventas_cubiertas.join(', ');
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `
                <h3>Pago #${pago.pago_id.slice(-5)}</h3>
                <p><b>Fecha:</b> ${fecha}</p>
                <p><b>Método de pago:</b> ${pago.metodo}</p>
                <p><b>Operador:</b> ${pago.operador}</p>
                <p><b>Monto:</b> $${pago.monto}</p>
                <p><b>Venta cubierta:</b> ${ventas}</p>
            `;
            list.appendChild(card);
        });
    }
}

document.getElementById('navPayments').addEventListener('click', () => {
    toggleSection('paymentsSection');
    loadPayments();
});


async function logout() {
    const user = getUser();
    if (!user) return;
    try {
        const res = await fetch(`/usuario/logout/user_id/${user.idUser}`, { method: 'DELETE' });
        if (res.ok) {
            const data = await res.json();
            alert(`Sesión cerrada. Categoría: ${data.categorizacion}`);
        }
    } catch {}
    localStorage.removeItem('user');
    setWelcome(null);
    toggleSection('productSection');
}

document.addEventListener('DOMContentLoaded', () => {
    loadProducts();
    const user = getUser();
    setWelcome(user);
    if (user) {
        toggleSection('productSection');
        loadCart();
        loadSales();
    }
    document.getElementById('showLogin').addEventListener('click', () => toggleSection('loginSection'));
    document.getElementById('showRegister').addEventListener('click', () => toggleSection('registerSection'));
    document.getElementById('navProducts').addEventListener('click', () => { toggleSection('productSection'); loadProducts(); });
    document.getElementById('navCart').addEventListener('click', () => { toggleSection('cartSection'); loadCart(); });
    document.getElementById('navSales').addEventListener('click', () => { toggleSection('salesSection'); loadSales(); });
    document.getElementById('navProfile').addEventListener('click', () => { showProfile(); toggleSection('profileSection'); });
    document.getElementById('navAdmin').addEventListener('click', () => { toggleSection('adminSection'); });
    document.getElementById('navUtils').addEventListener('click', () => { toggleSection('utilsSection'); });
    document.getElementById('logoutBtn').addEventListener('click', logout);
    document.getElementById('payMethod').addEventListener('change', (e) => {
    document.getElementById('cardFields').classList.toggle('hidden', e.target.value !== 'Tarjeta');});
    document.getElementById('cardExp').addEventListener('input', function (e) {
        let val = e.target.value.replace(/\D/g, '');
        if (!val) {
            e.target.value = '';
            return;
        }
        if (val.length === 1) {
            if (val[0] !== '0' && val[0] !== '1') {
                e.target.value = '0' + val + '/';
            } else {
                e.target.value = val;
            }
        } else if (val.length === 2) {
            let mes = parseInt(val, 10);
            if (mes === 0) mes = 1;
            if (mes > 12) {
                mes = 12;
            }
            e.target.value = (mes < 10 ? '0' + mes : mes) + '/';
        } else if (val.length > 2) {
            let mes = parseInt(val.slice(0, 2), 10);
            if (mes === 0) mes = 1;
            if (mes > 12) mes = 12;
            let año = val.slice(2, 4);
            e.target.value = (mes < 10 ? '0' + mes : mes) + '/' + año;
        }
    });


    document.getElementById('loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData();
        fd.append('username', document.getElementById('loginUser').value);
        fd.append('password', document.getElementById('loginPass').value);
        const res = await fetch('/usuario/login', { method: 'POST', body: fd });
        if (res.ok) {
            const userData = await res.json();
            localStorage.setItem('user', JSON.stringify(userData));
            setWelcome(userData);
            toggleSection('productSection');
            loadCart();
            loadSales();
            showProfile();
        } else {
            alert('Error al iniciar sesión');
        }
    });

    document.getElementById('registerForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('regName').value;
    const last_name = document.getElementById('regLast').value;
    const user_name = document.getElementById('regUser').value;
    const password = document.getElementById('regPass').value;
    const dni = document.getElementById('regDni').value;
    const address = document.getElementById('regAddress').value;
    const iva_condition = document.getElementById('regIva').value;
    const payload = { name, last_name, user_name, password, dni, address, iva_condition };

    const res = await fetch('/usuario/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (res.ok) {
        const userData = await res.json();
        console.log('[DEBUG] Respuesta del backend:', userData);
        localStorage.setItem('user', JSON.stringify(userData));
        setWelcome(userData);
        toggleSection('productSection');
        loadCart();
        loadSales();
        showProfile();
        e.target.reset();
    } else {
        alert('Error al registrar');
    }
});

    document.getElementById('confirmCart').addEventListener('click', confirmCart);
    document.getElementById('deleteOrder').addEventListener('click', deleteOrder);
    document.getElementById('payForm').addEventListener('submit', payOrder);
    document.getElementById('payMethod').addEventListener('change', (e) => {
        document.getElementById('cardNumber').classList.toggle('hidden', e.target.value !== 'Tarjeta');
    });
    document.getElementById('checkHealth').addEventListener('click', checkHealth);
    document.getElementById('loadPrices').addEventListener('click', loadPrices);
    document.getElementById('viewCartHistory').addEventListener('click', loadCartHistory);
    document.getElementById('loadCards').addEventListener('click', loadCards);
    document.getElementById('addProductForm').addEventListener('submit', addProduct);
    document.getElementById('updateProductForm').addEventListener('submit', updateProduct);
    document.getElementById('deleteProductForm').addEventListener('submit', deleteProduct);
    document.getElementById('historyForm').addEventListener('submit', loadHistory);
});
function hideAllAdminSubsections() {
    document.querySelectorAll('.admin-subsection').forEach(sec => sec.classList.add('hidden'));
}
document.getElementById('showAddProduct').onclick = function() {
    hideAllAdminSubsections();
    document.getElementById('addProductSection').classList.remove('hidden');
};
document.getElementById('showUpdateProduct').onclick = function() {
    hideAllAdminSubsections();
    document.getElementById('updateProductSection').classList.remove('hidden');
};
document.getElementById('showDeleteProduct').onclick = function() {
    hideAllAdminSubsections();
    document.getElementById('deleteProductSection').classList.remove('hidden');
};
document.getElementById('showHistory').onclick = function() {
    hideAllAdminSubsections();
    document.getElementById('historySection').classList.remove('hidden');
};
if(document.getElementById('adminSection')) {
    document.getElementById('adminSection').addEventListener('sectionshown', () => {
        hideAllAdminSubsections();
        document.getElementById('addProductSection').classList.remove('hidden');
    });
}
document.getElementById('navAdmin').addEventListener('click', () => {
    hideAllAdminSubsections();
    document.getElementById('addProductSection').classList.remove('hidden');
});

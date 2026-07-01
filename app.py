<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Seren Chat Mini App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --tg-theme-bg-color: #17212b;
            --tg-theme-text-color: #f5f5f5;
            --tg-theme-button-color: #2481cc;
            --tg-theme-button-text-color: #ffffff;
            --tg-theme-hint-color: #708499;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--tg-theme-bg-color);
            color: var(--tg-theme-text-color);
            margin: 0;
            padding: 15px;
        }
        .header { text-align: center; padding-bottom: 15px; border-bottom: 1px solid var(--tg-theme-hint-color); }
        .header h1 { margin: 5px 0; font-size: 24px; color: #2481cc; }
        .nav-tabs { display: flex; justify-content: space-around; margin: 15px 0; background: #202b36; padding: 8px; border-radius: 8px; }
        .tab { color: var(--tg-theme-hint-color); cursor: pointer; padding: 6px 12px; font-weight: bold; font-size: 14px; }
        .tab.active { color: var(--tg-theme-button-text-color); background-color: var(--tg-theme-button-color); border-radius: 6px; }
        .page { display: none; }
        .page.active { display: block; }
        .card { background: #202b36; padding: 15px; border-radius: 10px; margin-bottom: 15px; }
        .card h3 { margin-top: 0; color: #2481cc; }
        .form-group { margin-bottom: 12px; }
        label { display: block; margin-bottom: 5px; font-size: 13px; color: var(--tg-theme-hint-color); }
        input, select { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #2f3e4e; background: #17212b; color: white; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background-color: var(--tg-theme-button-color); color: var(--tg-theme-button-text-color); border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }
        .badge { background: #ff3b30; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; float: right; }
    </style>
</head>
<body>

    <div class="header">
        <h1>Seren Chat</h1>
        <p id="user-welcome">Loading user session...</p>
    </div>

    <div class="nav-tabs">
        <div class="tab active" onclick="switchPage('dashboard')">Dashboard</div>
        <div class="tab" onclick="switchPage('targets')">Targets</div>
        <div class="tab" onclick="switchPage('subscription')">Plans</div>
        <div class="tab" onclick="switchPage('admin-panel')" id="admin-tab" style="display:none;">Admin</div>
    </div>

    <!-- 1. DASHBOARD PAGE -->
    <div id="dashboard" class="page active">
        <div class="card">
            <h3>Account Status <span id="sub-badge" class="badge">Inactive</span></h3>
            <div class="form-group">
                <label>Telegram Phone Number</label>
                <input type="text" id="phone" placeholder="+2348000000000">
            </div>
            <div id="credentials-section">
                <div class="form-group">
                    <label>API ID</label>
                    <input type="number" id="api-id" placeholder="123456">
                </div>
                <div class="form-group">
                    <label>API HASH</label>
                    <input type="text" id="api-hash" placeholder="abcdef123456...">
                </div>
                <button onclick="initiateAuth()">Connect Account & Get OTP</button>
            </div>
            <div id="otp-section" style="display:none;">
                <div class="form-group">
                    <label>Enter OTP Code</label>
                    <input type="text" id="otp-code" placeholder="12345">
                </div>
                <div class="form-group">
                    <label>2FA Password (If active)</label>
                    <input type="password" id="password-2fa" placeholder="Leave blank if none">
                </div>
                <button onclick="verifyAuth()">Verify & Submit</button>
            </div>
        </div>
    </div>

    <!-- 2. TARGETS PAGE -->
    <div id="targets" class="page">
        <div class="card">
            <h3>Automation Settings</h3>
            <div class="form-group">
                <label>Target Type</label>
                <select id="target-type"><option value="all">Groups Only</option></select>
            </div>
            <div class="form-group">
                <label>AI Typing Delay (Seconds)</label>
                <input type="number" id="delay-num" value="15">
            </div>
            <button onclick="alert('Settings saved locally!')">Save Configuration</button>
        </div>
    </div>

    <!-- 3. SUBSCRIPTION PAGE -->
    <div id="subscription" class="page">
        <div class="card">
            <h3>USDT (TON Network) Payment</h3>
            <p>Subscription costs <strong>$2 USDT per group/week</strong>.</p>
            <div class="form-group">
                <label>Admin USDT Wallet Address</label>
                <input type="text" value="UQAd3qqKMuMi-cZlMeEmO4NkAzLsvYPsiHYmt7zBdMVTB8Hc" readonly style="color:#4cd964;">
            </div>
            <p style="text-align: center;">Support ID: <strong>@Auwaldc</strong></p>
        </div>
    </div>

    <!-- 4. ADMIN PANEL -->
    <div id="admin-panel" class="page">
        <div class="card">
            <h3>Admin Panel</h3>
            <div class="form-group">
                <label>User Phone Number</label>
                <input type="text" id="admin-target-phone" placeholder="+234...">
            </div>
            <div class="form-group">
                <label>Allowed Groups (separated by comma)</label>
                <input type="text" id="admin-allowed-groups" placeholder="group1, group2">
            </div>
            <button onclick="adminToggleSub(true)" style="background:#4cd964; margin-bottom:5px;">Activate Userbot</button>
            <button onclick="adminToggleSub(false)" style="background:#ff3b30;">Deactivate Userbot</button>
        </div>
    </div>

    <script>
        const BACKEND_URL = "https://seren-chat-production.up.railway.app"; 

        const tg = window.Telegram.WebApp;
        tg.expand();

        const username = tg.initDataUnsafe?.user?.username || "";
        if (username.toLowerCase() === "auwaldc") {
            document.getElementById("admin-tab").style.display = "block";
            document.getElementById("user-welcome").innerText = "Hello Admin @Auwaldc!";
        } else {
            document.getElementById("user-welcome").innerText = username ? `Welcome @${username}` : "Welcome to Seren Chat";
        }

        function switchPage(pageId) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById(pageId).classList.add('active');
            event.currentTarget.classList.add('active');
        }

        async function initiateAuth() {
            const phone = document.getElementById("phone").value;
            const apiId = document.getElementById("api-id").value;
            const apiHash = document.getElementById("api-hash").value;

            const res = await fetch(`${BACKEND_URL}/api/auth/initiate`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ api_id: parseInt(apiId), api_hash: apiHash, phone_number: phone })
            });
            if(res.ok) {
                alert("OTP Sent! Check your Telegram App.");
                document.getElementById("credentials-section").style.display = "none";
                document.getElementById("otp-section").style.display = "block";
            } else { alert("Failed to send OTP."); }
        }

        async function verifyAuth() {
            const phone = document.getElementById("phone").value;
            const otp = document.getElementById("otp-code").value;
            const pass2fa = document.getElementById("password-2fa").value;

            const res = await fetch(`${BACKEND_URL}/api/auth/verify`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ phone_number: phone, otp_code: otp, password_2fa: pass2fa })
            });
            const data = await res.json();
            alert(data.message);
            if(res.ok) { location.reload(); }
        }

        async function adminToggleSub(status) {
            const targetPhone = document.getElementById("admin-target-phone").value;
            const groupsInput = document.getElementById("admin-allowed-groups").value;
            const groupsArray = groupsInput.split(",").map(g => g.trim());

            const res = await fetch(`${BACKEND_URL}/api/admin/subscription`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ admin_user: "Auwaldc", target_phone: targetPhone, status: status, allowed_groups: groupsArray })
            });
            const data = await res.json();
            alert(data.message);
        }
    </script>
</body>
</html>

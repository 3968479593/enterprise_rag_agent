<script setup>
import { inject, ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, register } from '@/api'

const router = useRouter()
const toast = inject('toast')

const tab = ref('login') // login | register
const username = ref('')
const password = ref('')
const confirmPwd = ref('')
const inviteCode = ref('')
const showInvite = ref(false)
const busy = ref(false)

async function doLogin() {
  if (!username.value.trim() || !password.value) {
    toast('请输入用户名和密码', 'warn')
    return
  }
  busy.value = true
  try {
    await login({ username: username.value.trim(), password: password.value })
    toast('登录成功', 'ok')
    router.replace('/chat')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function doRegister() {
  const u = username.value.trim()
  if (u.length < 2) {
    toast('用户名至少 2 位', 'warn')
    return
  }
  if (password.value.length < 6) {
    toast('密码至少 6 位', 'warn')
    return
  }
  if (password.value !== confirmPwd.value) {
    toast('两次输入的密码不一致', 'warn')
    return
  }
  busy.value = true
  try {
    const data = await register({
      username: u,
      password: password.value,
      invite_code: inviteCode.value.trim(),
    })
    toast(data.role === 'admin' ? '管理员注册成功，已自动登录' : '注册成功，已自动登录', 'ok')
    router.replace('/chat')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}

function resetForm() {
  password.value = ''
  confirmPwd.value = ''
  inviteCode.value = ''
  showInvite.value = false
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <div class="brand-mark">
          <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round">
            <path d="M7 7h10M7 11h10M7 15h6" />
          </svg>
        </div>
        <div>
          <div class="brand-name">企业文档智能客服</div>
          <div class="brand-sub">RAG · Agent · Evaluation</div>
        </div>
      </div>

      <div class="tabs">
        <button class="tab" :class="{ on: tab === 'login' }" :disabled="busy" @click="tab = 'login'">登录</button>
        <button class="tab" :class="{ on: tab === 'register' }" :disabled="busy" @click="tab = 'register'; resetForm()">
          注册
        </button>
      </div>

      <!-- 登录 -->
      <template v-if="tab === 'login'">
        <label class="label" for="l-user">用户名</label>
        <input id="l-user" v-model="username" class="input" placeholder="请输入用户名" autocomplete="username" @keydown.enter="doLogin" />
        <label class="label" for="l-pwd" style="margin-top: 12px">密码</label>
        <input id="l-pwd" v-model="password" type="password" class="input" placeholder="请输入密码" autocomplete="current-password" @keydown.enter="doLogin" />
        <button class="btn primary enter" :disabled="busy" @click="doLogin">
          {{ busy ? '登录中…' : '登录' }}
        </button>
        <p class="tip">管理员使用管理员账号登录后，自动获得知识库管理与评估权限。</p>
      </template>

      <!-- 注册 -->
      <template v-else>
        <label class="label" for="r-user">用户名</label>
        <input id="r-user" v-model="username" class="input" placeholder="2-20 位字母、数字、下划线或中文" autocomplete="username" />
        <label class="label" for="r-pwd" style="margin-top: 12px">密码</label>
        <input id="r-pwd" v-model="password" type="password" class="input" placeholder="至少 6 位" autocomplete="new-password" />
        <label class="label" for="r-pwd2" style="margin-top: 12px">确认密码</label>
        <input id="r-pwd2" v-model="confirmPwd" type="password" class="input" placeholder="再次输入密码" autocomplete="new-password" @keydown.enter="doRegister" />

        <div class="invite-row">
          <label class="invite-toggle">
            <input v-model="showInvite" type="checkbox" />
            <span>注册为管理员（需要注册码）</span>
          </label>
        </div>
        <input
          v-if="showInvite"
          v-model="inviteCode"
          class="input"
          placeholder="管理员注册码（ADMIN_API_KEY）"
          style="margin-top: 8px"
        />

        <button class="btn primary enter" :disabled="busy" @click="doRegister">
          {{ busy ? '注册中…' : '注册并登录' }}
        </button>
        <p class="tip">普通用户可直接注册；管理员注册码未配置时，只可注册普通用户。</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(160deg, #f4f6f9 0%, #e8f0f1 100%); padding: 20px;
}
.login-card {
  width: 400px; max-width: 100%; background: var(--surface); border: 1px solid var(--line);
  border-radius: 14px; box-shadow: 0 8px 32px rgba(16, 28, 46, .1); padding: 28px 26px;
}
.brand { display: flex; align-items: center; gap: 11px; margin-bottom: 22px; }
.brand-mark {
  width: 40px; height: 40px; border-radius: 11px; flex-shrink: 0;
  background: linear-gradient(135deg, #0d7f8c, #1aa3a0);
  display: flex; align-items: center; justify-content: center;
}
.brand-mark svg { width: 20px; height: 20px; }
.brand-name { font-size: 17px; font-weight: 700; }
.brand-sub { font-size: 11.5px; color: var(--ink-3); margin-top: 1px; }

.tabs { display: flex; background: #eef1f6; border-radius: 9px; padding: 3px; margin-bottom: 18px; }
.tab {
  flex: 1; border: none; background: transparent; padding: 8px 0; font-size: 13.5px;
  font-weight: 500; color: var(--ink-2); border-radius: 7px; cursor: pointer; transition: all .15s;
}
.tab.on { background: var(--surface); color: var(--accent); box-shadow: var(--shadow); font-weight: 600; }

.enter { width: 100%; justify-content: center; padding: 11px 0; font-size: 14px; margin-top: 18px; }
.tip { margin-top: 14px; font-size: 11.5px; color: var(--ink-3); line-height: 1.6; }
.invite-row { margin-top: 14px; }
.invite-toggle { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--ink-2); cursor: pointer; user-select: none; }
.invite-toggle input { accent-color: var(--accent); width: 14px; height: 14px; }
</style>

function confirmWithPassword(form, message) {
  if (!window.confirm(message)) return false;
  const pw = window.prompt("请输入你的登录密码以确认此操作：");
  if (!pw) return false;
  form.querySelector('input[name="confirm_password"]').value = pw;
  return true;
}

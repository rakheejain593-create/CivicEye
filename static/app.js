const form = document.getElementById("reportForm");
const imageInput = document.getElementById("imageInput");
const preview = document.getElementById("imagePreview");
const placeholder = document.getElementById("uploadPlaceholder");
const message = document.getElementById("message");
const analysisCard = document.getElementById("analysisCard");
const submitButton = document.getElementById("submitButton");

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  message.textContent = "";
  analysisCard.hidden = true;
  if (!file) {
    preview.hidden = true;
    placeholder.hidden = false;
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    imageInput.value = "";
    showMessage("Image is larger than 5 MB. Please choose a smaller image.", true);
    return;
  }
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  placeholder.hidden = true;
});

function showMessage(text, isError=false) {
  message.textContent = text;
  message.className = "message " + (isError ? "error" : "success");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
  }[c]));
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!imageInput.files[0]) return showMessage("Please choose an image.", true);
  if (!document.getElementById("locationInput").value.trim()) {
    return showMessage("Please enter the issue location.", true);
  }

  submitButton.disabled = true;
  submitButton.textContent = "AI is analyzing your image…";
  message.className = "message";
  message.textContent = "Sending image securely to the backend for AI analysis. This may take a few seconds.";
  analysisCard.hidden = true;

  try {
    const response = await fetch("/api/complaints", {
      method: "POST",
      body: new FormData(form)
    });
    const data = await response.json();

    if (!response.ok) {
      const technical = data.technical_message ? " Details: " + data.technical_message : "";
      throw new Error((data.error || "Something went wrong.") + technical);
    }

    const a = data.analysis;
    analysisCard.innerHTML = `
      <h3>✓ AI analysis complete</h3>
      <p><b>Category:</b> ${escapeHtml(a.category)}</p>
      <p><b>Description:</b> ${escapeHtml(a.description)}</p>
      <p><b>Suggested priority:</b> ${escapeHtml(a.priority)}</p>
      <p><b>Suggested department:</b> ${escapeHtml(a.department)}</p>
      <p><b>Report ID:</b> CE-${data.complaint.id}</p>`;
    analysisCard.hidden = false;
    showMessage(data.message);
    form.reset();
    preview.hidden = true;
    placeholder.hidden = false;
    await loadComplaints();
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = 'Analyze with AI & submit <span>→</span>';
  }
});

async function loadComplaints() {
  const tbody = document.getElementById("complaintRows");
  try {
    const response = await fetch("/api/complaints");
    const complaints = await response.json();

    document.getElementById("totalCount").textContent = complaints.length;
    document.getElementById("pendingCount").textContent = complaints.filter(x => x.status === "Pending").length;
    document.getElementById("progressCount").textContent = complaints.filter(x => x.status === "In progress").length;
    document.getElementById("resolvedCount").textContent = complaints.filter(x => x.status === "Resolved").length;

    if (!complaints.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No reports yet. Submit the first one above.</td></tr>';
      return;
    }

    tbody.innerHTML = complaints.map(item => `
      <tr>
        <td><div class="issue-cell"><img class="issue-thumb" src="${escapeHtml(item.image_url)}" alt=""><span>${escapeHtml(item.category)}</span></div></td>
        <td>${escapeHtml(item.location)}</td>
        <td><span class="pill ${escapeHtml(item.priority)}">${escapeHtml(item.priority)}</span></td>
        <td><select class="status-select" aria-label="Update status for report ${item.id}" onchange="updateStatus(${item.id}, this.value)">
          ${["Pending","In progress","Resolved"].map(s => `<option ${item.status===s?"selected":""}>${s}</option>`).join("")}
        </select></td>
        <td>${escapeHtml(item.created_at)}</td>
      </tr>`).join("");
  } catch {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Could not load reports. Refresh the page.</td></tr>';
  }
}

async function updateStatus(id, status) {
  try {
    const response = await fetch(`/api/complaints/${id}`, {
      method: "PATCH",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({status})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Update failed");
    await loadComplaints();
  } catch (error) {
    alert(error.message);
  }
}

document.getElementById("refreshButton").addEventListener("click", loadComplaints);
loadComplaints();


// CivicEye AI chatbot
const chatLauncher = document.getElementById("chatLauncher");
const chatPanel = document.getElementById("chatPanel");
const chatClose = document.getElementById("chatClose");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatMessages = document.getElementById("chatMessages");
const chatSend = document.getElementById("chatSend");

function toggleChat(open) {
  chatPanel.hidden = !open;
  chatLauncher.setAttribute("aria-expanded", String(open));
  if (open) chatInput.focus();
}
chatLauncher.addEventListener("click", () => toggleChat(chatPanel.hidden));
chatClose.addEventListener("click", () => toggleChat(false));

function addChatBubble(text, who) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble " + (who === "user" ? "user-bubble" : "assistant-bubble");
  bubble.textContent = text; // textContent prevents HTML injection from model output
  chatMessages.appendChild(bubble);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return bubble;
}

document.querySelectorAll(".suggestion").forEach(button => {
  button.addEventListener("click", () => sendChatMessage(button.textContent));
});

async function sendChatMessage(message) {
  const clean = message.trim();
  if (!clean) return;
  document.getElementById("chatSuggestions")?.remove();
  addChatBubble(clean, "user");
  chatInput.value = "";
  chatInput.disabled = true;
  chatSend.disabled = true;
  const waiting = addChatBubble("Thinking…", "assistant");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: clean})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The assistant could not respond.");
    waiting.textContent = data.reply;
  } catch (error) {
    waiting.textContent = error.message;
  } finally {
    chatInput.disabled = false;
    chatSend.disabled = false;
    chatInput.focus();
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }
}

chatForm.addEventListener("submit", event => {
  event.preventDefault();
  sendChatMessage(chatInput.value);
});

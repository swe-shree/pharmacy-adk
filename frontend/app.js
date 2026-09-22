(() => {
  "use strict";

  // ============================================================
  // MEDICAL ASSISTANT
  // FRONTEND APP.JS
  // ============================================================

  // ============================================================
  // CONFIG
  // ============================================================

  const CONFIG = {
    API: "http://127.0.0.1:8001",
    VOICE: "ws://127.0.0.1:8001/voice/ws",
    USER_ID: "user_001",
  };


  // ============================================================
  // STATE
  // ============================================================

  let busy = false;
  let voiceState = "stopped";


  // ============================================================
  // DOM ELEMENTS
  // ============================================================

  const input =
    document.getElementById("message-input");

  const form =
    document.getElementById("chat-form");

  const sendBtn =
    document.getElementById("send-btn");

  const stream =
    document.getElementById("chat-stream");

  const typing =
    document.getElementById("typing-indicator");

  const micBtn =
    document.getElementById("input-mic-btn");

  const voicePill =
    document.getElementById("voice-status-pill");

  const voicePillText =
    document.getElementById("voice-status-text");

  const resetBtn =
    document.getElementById("reset-chat-btn");

  const cartBadge =
    document.getElementById("cart-badge");

  const cartItemsCount =
    document.getElementById("cart-items-count");

  const cartBtn =
    document.getElementById("cart-btn");

  const cartBackdrop =
    document.getElementById("cart-backdrop");

  const cartDrawer =
    document.getElementById("cart-drawer");

  const cartCloseBtn =
    document.getElementById("cart-close-btn");

  const emptyCartView =
    document.getElementById("empty-cart-view");

  const cartItemsList =
    document.getElementById("cart-items-list");

  const cartFooter =
    document.getElementById("cart-footer");

  const cartSubtotalAmount =
    document.getElementById("cart-subtotal-amount");

  const toastContainer =
    document.getElementById("toast-container");


  // ============================================================
  // DEBUG
  // ============================================================

  console.log("[PHARMACY] App loaded");

  console.log("[PHARMACY] API:", CONFIG.API);

  console.log(
    "[PHARMACY] Voice:",
    CONFIG.VOICE
  );

  console.log("[PHARMACY] DOM:", {
    input,
    form,
    sendBtn,
    stream,
    typing,
    micBtn,
    voicePill,
    voicePillText,
    resetBtn,
  });


  // ============================================================
  // TOAST
  // ============================================================

  function showToast(text, options) {
    if (!toastContainer || !text) {
      return;
    }

    const opts = options || {};

    const toast =
      document.createElement("div");

    toast.className = "toast";

    const icon =
      document.createElement("span");

    icon.className = "toast-icon";
    icon.textContent = "✓";
    icon.setAttribute("aria-hidden", "true");

    const label =
      document.createElement("span");

    label.className = "toast-text";
    label.textContent = text;

    toast.appendChild(icon);
    toast.appendChild(label);

    if (opts.actionLabel && typeof opts.onAction === "function") {
      const action =
        document.createElement("button");

      action.type = "button";
      action.className = "toast-action";
      action.textContent = opts.actionLabel;

      action.addEventListener("click", () => {
        opts.onAction();
        dismiss();
      });

      toast.appendChild(action);
    }

    toastContainer.appendChild(toast);

    // Force layout so the transition below actually animates in.
    requestAnimationFrame(() => {
      toast.classList.add("is-visible");
    });

    let dismissed = false;

    function dismiss() {
      if (dismissed) {
        return;
      }

      dismissed = true;

      toast.classList.remove("is-visible");

      setTimeout(() => {
        toast.remove();
      }, 240);
    }

    setTimeout(dismiss, opts.duration || 3200);
  }


  // ============================================================
  // CHAT SCROLL
  // ============================================================

  function scrollChat() {
    if (!stream) {
      return;
    }

    stream.scrollTop =
      stream.scrollHeight;
  }


  // ============================================================
  // ADD CHAT MESSAGE
  // ============================================================

  function addMessage(
    role,
    text
  ) {
    if (!stream) {
      console.warn(
        "[CHAT] #chat-stream not found"
      );

      return null;
    }

    if (
      text === null ||
      text === undefined
    ) {
      return null;
    }

    const messageText =
      String(text).trim();

    if (!messageText) {
      return null;
    }


    // ----------------------------------------------------------
    // Wrapper
    // ----------------------------------------------------------

    const wrapper =
      document.createElement("div");

    wrapper.className =
      `chat-bubble-wrapper ${role}`;


    // ----------------------------------------------------------
    // Avatar
    // ----------------------------------------------------------

    const avatar =
      document.createElement("div");

    avatar.className =
      `avatar ${role}-avatar`;

    avatar.textContent =
      role === "assistant"
        ? "✚"
        : "U";


    // ----------------------------------------------------------
    // Layout
    // ----------------------------------------------------------

    const layout =
      document.createElement("div");

    layout.className =
      "bubble-layout";


    // ----------------------------------------------------------
    // Sender
    // ----------------------------------------------------------

    const sender =
      document.createElement("span");

    sender.className =
      "sender-name";

    sender.textContent =
      role === "assistant"
        ? "Medical Assistant"
        : "You";


    // ----------------------------------------------------------
    // Message
    // ----------------------------------------------------------

    const bubble =
      document.createElement("div");

    bubble.className =
      "bubble-text";

    bubble.textContent =
      messageText;


    // ----------------------------------------------------------
    // Timestamp
    // ----------------------------------------------------------

    const timestamp =
      document.createElement("time");

    timestamp.className =
      "message-timestamp";

    timestamp.textContent =
      new Date().toLocaleTimeString(
        [],
        {
          hour: "2-digit",
          minute: "2-digit",
        }
      );


    // ----------------------------------------------------------
    // Build
    // ----------------------------------------------------------

    layout.appendChild(sender);

    layout.appendChild(bubble);

    layout.appendChild(timestamp);

    wrapper.appendChild(avatar);

    wrapper.appendChild(layout);

    stream.appendChild(wrapper);


    // ----------------------------------------------------------
    // Scroll
    // ----------------------------------------------------------

    scrollChat();

    return layout;
  }


  // ============================================================
  // TYPING INDICATOR
  // ============================================================

  function showTyping() {
    if (!typing) {
      return;
    }

    typing.hidden = false;

    typing.setAttribute(
      "aria-hidden",
      "false"
    );

    scrollChat();
  }


  function hideTyping() {
    if (!typing) {
      return;
    }

    typing.hidden = true;

    typing.setAttribute(
      "aria-hidden",
      "true"
    );
  }


  // ============================================================
  // CART BADGE
  // ============================================================

  async function refreshCartBadge() {
    try {

      const response =
        await fetch(
          `${CONFIG.API}/cart?user_id=${
            encodeURIComponent(CONFIG.USER_ID)
          }`
        );

      const data =
        await response.json();

      if (!data || data.success === false) {
        return;
      }

      const count =
        Number(data.item_count) || 0;

      if (cartBadge) {

        const changed =
          cartBadge.textContent !== String(count);

        cartBadge.textContent =
          String(count);

        if (changed) {
          cartBadge.classList.remove("pulse");
          // eslint-disable-next-line no-unused-expressions
          void cartBadge.offsetWidth;
          cartBadge.classList.add("pulse");
        }
      }

      if (cartItemsCount) {
        cartItemsCount.textContent =
          `(${count})`;
      }

    } catch (error) {

      console.warn(
        "[CART] refresh failed:",
        error
      );
    }
  }


  // ============================================================
  // CART DRAWER
  // ============================================================

  function renderCartItems(items) {

    if (!cartItemsList) {
      return;
    }

    const hasItems =
      Array.isArray(items) &&
      items.length > 0;


    // ----------------------------------------------------------
    // Empty state
    //
    // style.css sets `display: flex` on these classes, which beats
    // the browser's default `[hidden] { display: none }` rule -- so
    // the `hidden` attribute alone doesn't actually hide them here.
    // Set the inline display explicitly instead.
    // ----------------------------------------------------------

    if (emptyCartView) {
      emptyCartView.hidden =
        hasItems;

      emptyCartView.style.display =
        hasItems ? "none" : "";
    }

    if (cartFooter) {
      cartFooter.hidden =
        !hasItems;

      cartFooter.style.display =
        hasItems ? "" : "none";
    }

    if (!hasItems) {
      cartItemsList.hidden = true;
      cartItemsList.style.display = "none";
      cartItemsList.innerHTML = "";
      return;
    }


    // ----------------------------------------------------------
    // Item rows
    // ----------------------------------------------------------

    cartItemsList.hidden = false;
    cartItemsList.style.display = "";
    cartItemsList.innerHTML = "";

    let subtotal = 0;

    for (const item of items) {

      const quantity =
        Number(item.quantity) || 0;

      const unitPrice =
        Number(item.unit_price) || 0;

      subtotal +=
        quantity * unitPrice;

      const row =
        document.createElement("div");

      row.className = "cart-item-row";

      const info =
        document.createElement("div");

      const name =
        document.createElement("div");

      name.className = "cart-item-name";

      name.textContent =
        item.product_name || "Product";

      const meta =
        document.createElement("div");

      meta.className = "cart-item-meta";

      meta.textContent =
        `Qty ${quantity}` +
        (item.pharmacy_name
          ? ` · ${item.pharmacy_name}`
          : "");

      info.appendChild(name);
      info.appendChild(meta);

      const price =
        document.createElement("div");

      price.className = "cart-item-price";

      price.textContent =
        `₹${(quantity * unitPrice).toFixed(2)}`;

      row.appendChild(info);
      row.appendChild(price);

      cartItemsList.appendChild(row);
    }

    if (cartSubtotalAmount) {
      cartSubtotalAmount.textContent =
        `₹${subtotal.toFixed(2)}`;
    }
  }


  async function openCart() {

    if (cartBackdrop) {
      cartBackdrop.classList.add("is-open");
      cartBackdrop.setAttribute(
        "aria-hidden",
        "false"
      );
    }

    if (cartDrawer) {
      cartDrawer.classList.add("is-open");
      cartDrawer.setAttribute(
        "aria-hidden",
        "false"
      );
    }

    try {

      const response =
        await fetch(
          `${CONFIG.API}/cart?user_id=${
            encodeURIComponent(CONFIG.USER_ID)
          }`
        );

      const data =
        await response.json();

      if (!data || data.success === false) {
        renderCartItems([]);
        return;
      }

      renderCartItems(data.items);

      const count =
        Number(data.item_count) || 0;

      if (cartBadge) {
        cartBadge.textContent =
          String(count);
      }

      if (cartItemsCount) {
        cartItemsCount.textContent =
          `(${count})`;
      }

    } catch (error) {

      console.warn(
        "[CART] load failed:",
        error
      );

      renderCartItems([]);
    }
  }


  function closeCart() {

    if (cartBackdrop) {
      cartBackdrop.classList.remove("is-open");
      cartBackdrop.setAttribute(
        "aria-hidden",
        "true"
      );
    }

    if (cartDrawer) {
      cartDrawer.classList.remove("is-open");
      cartDrawer.setAttribute(
        "aria-hidden",
        "true"
      );
    }
  }


  if (cartBtn) {

    cartBtn.addEventListener(
      "click",
      () => {
        openCart();
      }
    );
  }

  if (cartCloseBtn) {

    cartCloseBtn.addEventListener(
      "click",
      closeCart
    );
  }

  if (cartBackdrop) {

    cartBackdrop.addEventListener(
      "click",
      closeCart
    );
  }


  // ============================================================
  // ASSISTANT REPLY HANDLING
  // (toast for cart/order confirmations from assistant voice/text replies)
  // ============================================================

  function extractAddedToCartProduct(text) {

    const value =
      String(text || "");

    // Active phrasing: "Added Dolo 650 to your cart." / "I've added
    // 2 x Dolo 650 to your cart."
    const active =
      /\badded\s+(?:\d+\s*x\s*)?(.+?)\s+to\s+(?:your|the)\s+cart/i.exec(
        value
      );

    if (active) {
      return active[1].trim();
    }

    // Passive phrasing: "Dolo 650 has been added to your cart."
    const passive =
      /(.+?)\s+(?:has|have|is|was)\s+(?:been\s+)?added\s+to\s+(?:your|the)\s+cart/i.exec(
        value
      );

    return passive ? passive[1].trim() : null;
  }

  function looksLikeOrderConfirmation(text) {
    return /\border\b[^.!?]*\b(placed|confirmed|successfully)\b/i.test(
      String(text || "")
    );
  }

  function handleAssistantReply(text) {

    addMessage("assistant", text);

    const addedProduct =
      extractAddedToCartProduct(text);

    if (addedProduct) {

      showToast(
        `${addedProduct} added to cart`,
        {
          actionLabel: "View Cart",
          onAction: openCart,
        }
      );

    } else if (looksLikeOrderConfirmation(text)) {

      showToast("Order placed successfully");
    }
  }


  // ============================================================
  // SEND BUTTON STATE
  // ============================================================

  function updateSendButton() {
    if (!sendBtn) {
      return;
    }

    const hasText =
      !!input &&
      input.value.trim().length > 0;

    const enabled =
      hasText && !busy;

    sendBtn.disabled =
      !enabled;

    sendBtn.classList.toggle(
      "active",
      enabled
    );
  }


  // ============================================================
  // CHAT API
  // ============================================================

  async function sendMessage(
    value
  ) {
    const message =
      String(value || "").trim();

    if (!message) {
      return;
    }

    if (busy) {
      return;
    }


    // ----------------------------------------------------------
    // Lock
    // ----------------------------------------------------------

    busy = true;

    updateSendButton();


    // ----------------------------------------------------------
    // Clear input
    // ----------------------------------------------------------

    if (input) {
      input.value = "";
    }

    updateSendButton();


    // ----------------------------------------------------------
    // Show user message
    // ----------------------------------------------------------

    addMessage(
      "user",
      message
    );


    // ----------------------------------------------------------
    // Typing
    // ----------------------------------------------------------

    showTyping();


    try {

      console.log(
        "[CHAT] Sending:",
        message
      );


      // --------------------------------------------------------
      // API REQUEST
      // --------------------------------------------------------

      const response =
        await fetch(
          `${CONFIG.API}/chat`,
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json",
            },

            body: JSON.stringify({
              user_id:
                CONFIG.USER_ID,

              session_id:
                CONFIG.USER_ID,

              message:
                message,
            }),
          }
        );


      console.log(
        "[CHAT] HTTP status:",
        response.status
      );


      // --------------------------------------------------------
      // Parse response
      // --------------------------------------------------------

      let data;

      try {

        data =
          await response.json();

      } catch (parseError) {

        const raw =
          await response.text();

        throw new Error(
          `Invalid backend response: ${raw}`
        );
      }


      console.log(
        "[CHAT] Backend response:",
        data
      );


      // --------------------------------------------------------
      // Backend error
      // --------------------------------------------------------

      if (!response.ok) {

        throw new Error(
          data?.error ||
          data?.message ||
          `Backend error ${response.status}`
        );
      }


      if (
        data &&
        data.success === false
      ) {

        throw new Error(
          data.error ||
          data.message ||
          "Backend request failed."
        );
      }


      // --------------------------------------------------------
      // Get assistant response
      // --------------------------------------------------------

      let assistantText = null;


      if (
        typeof data === "string"
      ) {

        assistantText =
          data;

      } else if (
        data?.response
      ) {

        assistantText =
          data.response;

      } else if (
        data?.message
      ) {

        assistantText =
          data.message;

      } else if (
        data?.text
      ) {

        assistantText =
          data.text;

      } else if (
        data?.answer
      ) {

        assistantText =
          data.answer;

      } else if (
        data?.output
      ) {

        assistantText =
          data.output;

      } else if (
        data?.result?.response
      ) {

        assistantText =
          data.result.response;

      } else if (
        data?.result?.message
      ) {

        assistantText =
          data.result.message;

      } else if (
        data?.result?.text
      ) {

        assistantText =
          data.result.text;
      }


      // --------------------------------------------------------
      // Empty response
      // --------------------------------------------------------

      if (
        !assistantText ||
        !String(
          assistantText
        ).trim()
      ) {

        throw new Error(
          "Backend returned an empty response."
        );
      }


      // --------------------------------------------------------
      // Show response
      // --------------------------------------------------------

      hideTyping();

      handleAssistantReply(
        assistantText
      );

      refreshCartBadge();

    } catch (error) {

      console.error(
        "[CHAT] Error:",
        error
      );

      hideTyping();


      addMessage(
        "assistant",
        `Sorry, I couldn't get a response. ${
          error?.message ||
          "Please try again."
        }`
      );

    } finally {

      busy = false;

      updateSendButton();

      if (input) {
        input.focus();
      }
    }
  }


  // ============================================================
  // CHAT FORM
  // ============================================================

  if (form) {

    form.addEventListener(
      "submit",
      async (event) => {

        event.preventDefault();

        if (!input) {
          return;
        }

        await sendMessage(
          input.value
        );
      }
    );

  } else {

    console.warn(
      "[CHAT] #chat-form not found"
    );
  }


  // ============================================================
  // INPUT EVENT
  // ============================================================

  if (input) {

    input.addEventListener(
      "input",
      () => {
        updateSendButton();
      }
    );


    // ----------------------------------------------------------
    // ENTER TO SEND
    // ----------------------------------------------------------

    input.addEventListener(
      "keydown",
      async (event) => {

        if (
          event.key === "Enter" &&
          !event.shiftKey
        ) {

          event.preventDefault();

          await sendMessage(
            input.value
          );
        }
      }
    );
  }


  // ============================================================
  // SEND BUTTON
  // ============================================================

  if (sendBtn) {

    sendBtn.addEventListener(
      "click",
      async (event) => {

        event.preventDefault();

        if (!input) {
          return;
        }

        const text =
          input.value.trim();

        if (!text) {
          return;
        }

        await sendMessage(text);
      }
    );
  }


  // ============================================================
  // RESET CHAT
  // ============================================================

  if (resetBtn) {

    resetBtn.addEventListener(
      "click",
      () => {

        if (!stream) {
          return;
        }

        stream.innerHTML = `
          <div class="chat-bubble-wrapper assistant">
            <div class="avatar assistant-avatar">
              ✚
            </div>

            <div class="bubble-layout">
              <span class="sender-name">
                Medical Assistant
              </span>

              <div class="bubble-text">
                Hi! How can I help you today?
              </div>

              <time class="message-timestamp">
                ${new Date().toLocaleTimeString(
                  [],
                  {
                    hour: "2-digit",
                    minute: "2-digit",
                  }
                )}
              </time>
            </div>
          </div>
        `;

        scrollChat();
      }
    );
  }


  // ============================================================
  // VOICE STATE
  // ============================================================

  function setVoiceState(
    nextState
  ) {

    voiceState =
      nextState;


    const labels = {
      stopped: "Voice off",
      connecting: "Connecting…",
      listening: "Listening",
      speaking: "Speaking",
    };

    const label =
      labels[nextState] ||
      labels.stopped;


    // ----------------------------------------------------------
    // Mic button (lives inside the chat input)
    // ----------------------------------------------------------

    if (micBtn) {

      micBtn.classList.toggle(
        "active",
        nextState !== "stopped"
      );

      micBtn.setAttribute(
        "aria-pressed",
        String(
          nextState !== "stopped"
        )
      );
    }


    // ----------------------------------------------------------
    // Compact status pill
    // ----------------------------------------------------------

    if (voicePillText) {

      voicePillText.textContent =
        label;
    }

    if (voicePill) {

      voicePill.className =
        `voice-status-pill state-${nextState}`;
    }
  }


  // ============================================================
  // VOICE BRIDGE
  // ============================================================

  const VoiceBridge = {

    socket: null,

    audioContext: null,

    playbackContext: null,

    mediaStream: null,

    source: null,

    processor: null,

    nextPlaybackTime: 0,


    // ==========================================================
    // START
    // ==========================================================

    async start() {

      if (this.socket) {
        return;
      }


      setVoiceState(
        "connecting"
      );


      const voiceUrl =
        `${CONFIG.VOICE}?user_id=${
          encodeURIComponent(CONFIG.USER_ID)
        }&session_id=${
          encodeURIComponent(CONFIG.USER_ID)
        }`;

      console.log(
        "[VoiceBridge] Connecting:",
        voiceUrl
      );


      const socket =
        new WebSocket(
          voiceUrl
        );


      socket.binaryType =
        "arraybuffer";


      this.socket =
        socket;


      // ========================================================
      // OPEN
      // ========================================================

      socket.onopen =
        async () => {

          console.log(
            "[VoiceBridge] WebSocket connected"
          );

          try {

            await this.startMicrophone();

            setVoiceState(
              "listening"
            );

          } catch (error) {

            console.error(
              "[VoiceBridge] Microphone error:",
              error
            );

            addMessage(
              "assistant",
              `Microphone error: ${
                error?.message ||
                "Permission denied"
              }`
            );

            this.stop();
          }
        };


      // ========================================================
      // MESSAGE
      // ========================================================

      socket.onmessage =
        async (event) => {

          // ----------------------------------------------------
          // JSON MESSAGE
          // ----------------------------------------------------

          if (
            typeof event.data ===
            "string"
          ) {

            let message;

            try {

              message =
                JSON.parse(
                  event.data
                );

            } catch (error) {

              console.warn(
                "[VoiceBridge] Invalid JSON:",
                event.data
              );

              return;
            }


            console.log(
              "[VoiceBridge] Server message:",
              message
            );


            // --------------------------------------------------
            // Connected
            // --------------------------------------------------

            if (
              message.type ===
              "connected"
            ) {

              setVoiceState(
                "listening"
              );
            }


            // --------------------------------------------------
            // User transcript
            // --------------------------------------------------

            if (
              message.type ===
                "user_transcript" &&
              message.text
            ) {

              addMessage(
                "user",
                message.text
              );
            }


            // --------------------------------------------------
            // Assistant text
            // --------------------------------------------------

            if (
              message.type ===
                "assistant_text" &&
              message.text
            ) {

              handleAssistantReply(
                message.text
              );
            }


            // --------------------------------------------------
            // Assistant transcript
            // --------------------------------------------------

            if (
              message.type ===
                "assistant_transcript" &&
              message.text
            ) {

              handleAssistantReply(
                message.text
              );
            }


            // --------------------------------------------------
            // Turn complete
            // --------------------------------------------------

            if (
              message.type ===
              "turn_complete"
            ) {

              setVoiceState(
                "listening"
              );

              refreshCartBadge();
            }


            // --------------------------------------------------
            // Error
            // --------------------------------------------------

            if (
              message.type ===
              "error"
            ) {

              console.error(
                "[VoiceBridge] Server error:",
                message.message
              );

              addMessage(
                "assistant",
                `Voice error: ${
                  message.message ||
                  "Unknown voice error"
                }`
              );

              this.stop();
            }

            return;
          }


          // ----------------------------------------------------
          // AUDIO
          // ----------------------------------------------------

          if (
            event.data instanceof
            ArrayBuffer
          ) {

            await this.playAudio(
              event.data
            );

            return;
          }


          // ----------------------------------------------------
          // BLOB AUDIO
          // ----------------------------------------------------

          if (
            event.data instanceof Blob
          ) {

            const buffer =
              await event.data.arrayBuffer();

            await this.playAudio(
              buffer
            );
          }
        };


      // ========================================================
      // ERROR
      // ========================================================

      socket.onerror =
        (error) => {

          console.error(
            "[VoiceBridge] WebSocket error:",
            error
          );
        };


      // ========================================================
      // CLOSE
      // ========================================================

      socket.onclose =
        (event) => {

          console.log(
            "[VoiceBridge] WebSocket closed:",
            event.code,
            event.reason
          );

          this.cleanupAudio();

          this.socket = null;

          setVoiceState(
            "stopped"
          );
        };
    },


    // ==========================================================
    // START MICROPHONE
    // ==========================================================

    async startMicrophone() {

      console.log(
        "[VoiceBridge] Requesting microphone..."
      );


      this.mediaStream =
        await navigator.mediaDevices
          .getUserMedia({
            audio: {
              channelCount: 1,

              echoCancellation:
                true,

              noiseSuppression:
                true,

              autoGainControl:
                true,
            },
          });


      console.log(
        "[VoiceBridge] Microphone permission granted"
      );


      // --------------------------------------------------------
      // Audio Context
      // --------------------------------------------------------

      this.audioContext =
        new AudioContext();


      if (
        this.audioContext.state ===
        "suspended"
      ) {

        await this.audioContext.resume();
      }


      console.log(
        "[VoiceBridge] Input sample rate:",
        this.audioContext.sampleRate
      );


      // --------------------------------------------------------
      // Microphone Source
      // --------------------------------------------------------

      this.source =
        this.audioContext
          .createMediaStreamSource(
            this.mediaStream
          );


      // --------------------------------------------------------
      // Processor
      // --------------------------------------------------------

      this.processor =
        this.audioContext
          .createScriptProcessor(
            4096,
            1,
            1
          );


      this.processor.onaudioprocess =
        (event) => {

          if (
            !this.socket ||
            this.socket.readyState !==
              WebSocket.OPEN
          ) {

            return;
          }


          const input =
            event.inputBuffer
              .getChannelData(0);


          const pcm16 =
            this.resampleTo16k(
              input
            );


          if (
            pcm16 &&
            pcm16.byteLength > 0
          ) {

            this.socket.send(
              pcm16
            );
          }
        };


      // --------------------------------------------------------
      // Connect nodes
      // --------------------------------------------------------

      this.source.connect(
        this.processor
      );


      this.processor.connect(
        this.audioContext.destination
      );


      console.log(
        "[VoiceBridge] Microphone started"
      );
    },


    // ==========================================================
    // RESAMPLE TO 16 KHZ
    // ==========================================================

    resampleTo16k(
      input
    ) {

      if (
        !this.audioContext
      ) {

        return new ArrayBuffer(0);
      }


      const inputSampleRate =
        this.audioContext.sampleRate;


      const outputSampleRate =
        16000;


      if (
        inputSampleRate ===
        outputSampleRate
      ) {

        return this.floatTo16BitPCM(
          input
        );
      }


      const ratio =
        inputSampleRate /
        outputSampleRate;


      const outputLength =
        Math.floor(
          input.length /
          ratio
        );


      const output =
        new Int16Array(
          outputLength
        );


      for (
        let i = 0;
        i < outputLength;
        i++
      ) {

        const index =
          Math.floor(
            i * ratio
          );


        const sample =
          Math.max(
            -1,
            Math.min(
              1,
              input[index]
            )
          );


        output[i] =
          sample < 0
            ? sample * 0x8000
            : sample * 0x7fff;
      }


      return output.buffer;
    },


    // ==========================================================
    // FLOAT -> PCM16
    // ==========================================================

    floatTo16BitPCM(
      input
    ) {

      const output =
        new Int16Array(
          input.length
        );


      for (
        let i = 0;
        i < input.length;
        i++
      ) {

        const sample =
          Math.max(
            -1,
            Math.min(
              1,
              input[i]
            )
          );


        output[i] =
          sample < 0
            ? sample * 0x8000
            : sample * 0x7fff;
      }


      return output.buffer;
    },


    // ==========================================================
    // PLAY GEMINI AUDIO
    // ==========================================================

    async playAudio(
      arrayBuffer
    ) {

      try {

        if (
          !this.playbackContext
        ) {

          this.playbackContext =
            new AudioContext();
        }


        if (
          this.playbackContext.state ===
          "suspended"
        ) {

          await this.playbackContext.resume();
        }


        // ------------------------------------------------------
        // Gemini Live output:
        // PCM16 / 24kHz
        // ------------------------------------------------------

        const pcm16 =
          new Int16Array(
            arrayBuffer
          );


        if (
          pcm16.length === 0
        ) {

          return;
        }


        const audioBuffer =
          this.playbackContext
            .createBuffer(
              1,
              pcm16.length,
              24000
            );


        const channel =
          audioBuffer.getChannelData(
            0
          );


        for (
          let i = 0;
          i < pcm16.length;
          i++
        ) {

          channel[i] =
            pcm16[i] /
            32768;
        }


        const source =
          this.playbackContext
            .createBufferSource();


        source.buffer =
          audioBuffer;


        source.connect(
          this.playbackContext.destination
        );


        const now =
          this.playbackContext
            .currentTime;


        this.nextPlaybackTime =
          Math.max(
            this.nextPlaybackTime,
            now
          );


        source.start(
          this.nextPlaybackTime
        );


        this.nextPlaybackTime +=
          audioBuffer.duration;


        setVoiceState(
          "speaking"
        );


        source.onended =
          () => {

            if (
              this.playbackContext &&
              this.nextPlaybackTime <=
                this.playbackContext
                  .currentTime +
                0.05
            ) {

              setVoiceState(
                "listening"
              );
            }
          };

      } catch (error) {

        console.error(
          "[VoiceBridge] Audio playback error:",
          error
        );
      }
    },


    // ==========================================================
    // CLEANUP AUDIO
    // ==========================================================

    cleanupAudio() {

      try {

        if (
          this.processor
        ) {

          this.processor.disconnect();
        }

      } catch (error) {
        console.warn(
          "[VoiceBridge] Processor cleanup:",
          error
        );
      }


      try {

        if (
          this.source
        ) {

          this.source.disconnect();
        }

      } catch (error) {
        console.warn(
          "[VoiceBridge] Source cleanup:",
          error
        );
      }


      this.processor =
        null;

      this.source =
        null;


      // --------------------------------------------------------
      // Stop microphone
      // --------------------------------------------------------

      if (
        this.mediaStream
      ) {

        this.mediaStream
          .getTracks()
          .forEach(
            (track) => {
              track.stop();
            }
          );
      }


      this.mediaStream =
        null;


      // --------------------------------------------------------
      // Close input audio context
      // --------------------------------------------------------

      if (
        this.audioContext
      ) {

        this.audioContext
          .close()
          .catch(() => {});
      }


      this.audioContext =
        null;


      this.nextPlaybackTime =
        0;
    },


    // ==========================================================
    // STOP
    // ==========================================================

    stop() {

      console.log(
        "[VoiceBridge] Stopping voice..."
      );


      this.cleanupAudio();


      if (
        this.socket
      ) {

        try {

          this.socket.close();

        } catch (error) {

          console.warn(
            "[VoiceBridge] Socket close:",
            error
          );
        }
      }


      this.socket =
        null;


      // --------------------------------------------------------
      // Close playback
      // --------------------------------------------------------

      if (
        this.playbackContext
      ) {

        this.playbackContext
          .close()
          .catch(() => {});
      }


      this.playbackContext =
        null;


      setVoiceState(
        "stopped"
      );
    },
  };


  // ============================================================
  // VOICE TOGGLE
  // ============================================================

  async function toggleVoice() {

    if (
      voiceState ===
      "stopped"
    ) {

      await VoiceBridge.start();

    } else {

      VoiceBridge.stop();
    }
  }


  // ============================================================
  // INPUT MIC BUTTON (sole voice control, lives in the chat input)
  // ============================================================

  if (micBtn) {

    micBtn.addEventListener(
      "click",
      async () => {

        await toggleVoice();
      }
    );
  }


  // ============================================================
  // INITIAL STATE
  // ============================================================

  setVoiceState(
    "stopped"
  );

  updateSendButton();

  refreshCartBadge();


  console.log(
    "[PHARMACY] Application ready"
  );

})();

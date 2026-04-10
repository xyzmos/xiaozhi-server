import { uiController } from '../../ui/controller.js?v=0205';
import { log } from '../../utils/logger.js?v=0205';

const BRIDGE_URL_CANDIDATES = [
    `${window.location.origin}/events`
];

let wakewordEventSource = null;

export function startWakewordBridgeListener() {
    if (wakewordEventSource) {
        return wakewordEventSource;
    }

    log('正在连接本地唤醒事件桥...', 'info');
    tryConnect(0);
    return wakewordEventSource;
}

function tryConnect(index) {
    if (index >= BRIDGE_URL_CANDIDATES.length) {
        log('未能连接到本地唤醒事件桥，请确认 test runtime 已启动', 'warning');
        return null;
    }

    const bridgeUrl = BRIDGE_URL_CANDIDATES[index];

    try {
        wakewordEventSource = new EventSource(bridgeUrl);
        wakewordEventSource.onopen = () => {
            log(`本地唤醒事件桥已连接: ${bridgeUrl}`, 'success');
        };

        wakewordEventSource.onmessage = async (event) => {
            try {
                const message = JSON.parse(event.data);
                if (message.type === 'bridge_connected') {
                    log('本地唤醒监听已就绪', 'info');
                    return;
                }

                if (message.type === 'service_ready') {
                    log('本地唤醒服务已启动', 'info');
                    return;
                }

                if (message.type === 'service_stopping') {
                    log('本地唤醒服务正在停止', 'warning');
                    return;
                }

                if (message.type === 'wake_word_detected') {
                    const wakeWord = message.payload?.wake_word || '唤醒词';
                    log(`检测到本地唤醒事件: ${wakeWord}`, 'info');
                    await uiController.triggerWakewordDial(wakeWord);
                }
            } catch (error) {
                log(`解析本地唤醒事件失败: ${error.message}`, 'error');
            }
        };

        wakewordEventSource.onerror = () => {
            log(`本地唤醒事件桥连接异常: ${bridgeUrl}`, 'warning');
            if (wakewordEventSource) {
                wakewordEventSource.close();
                wakewordEventSource = null;
            }

            if (index + 1 < BRIDGE_URL_CANDIDATES.length) {
                log(`尝试备用地址: ${BRIDGE_URL_CANDIDATES[index + 1]}`, 'info');
                tryConnect(index + 1);
                return;
            }

            log('请确认当前页面由 test runtime 启动，并且 /events 可访问', 'warning');
        };

        return wakewordEventSource;
    } catch (error) {
        log(`启动本地唤醒监听失败: ${error.message}`, 'error');
        return tryConnect(index + 1);
    }
}

export function stopWakewordBridgeListener() {
    if (!wakewordEventSource) {
        return;
    }

    wakewordEventSource.close();
    wakewordEventSource = null;
}
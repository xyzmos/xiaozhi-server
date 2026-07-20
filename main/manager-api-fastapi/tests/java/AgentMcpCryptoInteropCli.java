import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;

import xiaozhi.common.utils.AESUtils;

public final class AgentMcpCryptoInteropCli {
    private AgentMcpCryptoInteropCli() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: AgentMcpCryptoInteropCli <agent-id> <key>");
        }
        byte[] digest = MessageDigest.getInstance("MD5").digest(args[0].getBytes(StandardCharsets.UTF_8));
        String json = "{\"agentId\": \"%s\"}".formatted(HexFormat.of().formatHex(digest));
        System.out.print(AESUtils.encrypt(args[1], json));
    }
}

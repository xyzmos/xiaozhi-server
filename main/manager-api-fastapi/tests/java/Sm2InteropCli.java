import xiaozhi.common.utils.SM2Utils;

/** Tiny subprocess boundary used by the Python/Java SM2 interoperability tests. */
public final class Sm2InteropCli {
    private Sm2InteropCli() {
    }

    public static void main(String[] args) {
        if (args.length != 3) {
            throw new IllegalArgumentException("usage: encrypt <public-key> <plaintext> | decrypt <private-key> <ciphertext>");
        }
        switch (args[0]) {
            case "encrypt" -> System.out.print(SM2Utils.encrypt(args[1], args[2]));
            case "decrypt" -> System.out.print(SM2Utils.decrypt(args[1], args[2]));
            default -> throw new IllegalArgumentException("unknown operation: " + args[0]);
        }
    }
}

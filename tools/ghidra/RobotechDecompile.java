// license:BSD-3-Clause
// copyright-holders:Sebastian Toyos
// Writes Ghidra's C of the functions at the addresses given, for reading (a post-script).
// Arguments: the folder to write to, then one hexadecimal address a function.
import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class RobotechDecompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File folder = new File(args[0]);
        folder.mkdirs();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        for (int i = 1; i < args.length; i++) {
            Address address = toAddr(Long.parseLong(args[i], 16));
            Function function = getFunctionContaining(address);
            if (function == null) {
                println("no function at " + args[i]);
                continue;
            }
            DecompileResults results = decompiler.decompileFunction(function, 180, monitor);
            String text = results.decompileCompleted() ? results.getDecompiledFunction().getC()
                    : "/* not decompiled: " + results.getErrorMessage() + " */\n";
            File file = new File(folder, String.format("%08X_%s.c", function.getEntryPoint().getOffset(), function.getName()));
            try (PrintWriter writer = new PrintWriter(file, "UTF-8")) {
                writer.print(text);
            }
            println("wrote " + file.getName() + ": " + text.length() + " characters, body "
                    + function.getBody().getNumAddresses() + " bytes");
        }
        decompiler.dispose();
    }
}

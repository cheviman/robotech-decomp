// license:BSD-3-Clause
// copyright-holders:Sebastian Toyos
// Marks the functions' starts and the names symbols.txt gives, before Ghidra's analysis (a pre-script).
// Argument: the list tools/ghidra/prepare.py writes ("func ADDRESS [NAME]", "data ADDRESS NAME").
import java.io.BufferedReader;
import java.io.FileReader;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class RobotechSeed extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        int functions = 0, labels = 0, failed = 0;
        // Ghidra takes functions that hand their results back in registers (GameObjectFromHandle,
        // vcObjectRelease...) for ones that never return, and ends their callers at the call
        try {
            setAnalysisOption(currentProgram, "Non-Returning Functions - Discovered", "false");
            println("the analysis of non-returning functions is off");
        } catch (Exception e) {
            println("could not turn the analysis of non-returning functions off: " + e.getMessage());
        }
        try (BufferedReader reader = new BufferedReader(new FileReader(args[0]))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String[] f = line.trim().split("\\s+");
                if (f.length < 2) {
                    continue;
                }
                Address address = toAddr(Long.parseLong(f[1], 16));
                try {
                    if (f[0].equals("func")) {
                        disassemble(address);
                        Function function = getFunctionAt(address);
                        if (function == null) {
                            function = createFunction(address, f.length > 2 ? f[2] : null);
                        } else if (f.length > 2) {
                            function.setName(f[2], SourceType.USER_DEFINED);
                        }
                        if (function == null) {
                            failed++;
                        } else {
                            functions++;
                        }
                    } else if (f[0].equals("data") && f.length > 2) {
                        createLabel(address, f[2], true, SourceType.USER_DEFINED);
                        labels++;
                    }
                } catch (Exception e) {
                    failed++;
                }
            }
        }
        println("seeded " + functions + " functions, " + labels + " labels, " + failed + " failed");
    }
}

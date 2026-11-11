// license:BSD-3-Clause
// copyright-holders:Sebastian Toyos
// Writes Ghidra's C of every function into one file, for reading and for searching (a post-script).
// Each function follows a line "// ==== ADDRESS NAME". First it clears the "does not return" mark Ghidra's
// analysis puts on functions that do return (vcObjectRelease, GameObjectDestroy...), which cut the C of
// their callers after the call: no function of the game's is known not to return.
// Argument: the file to write.
import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class RobotechDecompileAll extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        int cleared = 0;
        FunctionIterator all = currentProgram.getFunctionManager().getFunctions(true);
        while (all.hasNext()) {
            Function function = all.next();
            if (function.hasNoReturn()) {
                function.setNoReturn(false);
                cleared++;
            }
        }
        println("cleared the no-return mark of " + cleared + " functions");

        File file = new File(args[0]);
        file.getParentFile().mkdirs();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int written = 0, failed = 0;
        try (PrintWriter writer = new PrintWriter(file, "UTF-8")) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext() && !monitor.isCancelled()) {
                Function function = functions.next();
                DecompileResults results = decompiler.decompileFunction(function, 60, monitor);
                writer.println(String.format("// ==== %08X %s", function.getEntryPoint().getOffset(), function.getName()));
                if (results.decompileCompleted()) {
                    writer.print(results.getDecompiledFunction().getC());
                    written++;
                } else {
                    writer.println("/* not decompiled: " + results.getErrorMessage() + " */");
                    failed++;
                }
            }
        }
        decompiler.dispose();
        println("wrote " + written + " functions, " + failed + " not decompiled, to " + file.getName());
    }
}

// license:BSD-3-Clause
// copyright-holders:Sebastian Toyos
// Gives Ghidra what symbols.txt and tools/decompile.py know: the structures, the variables' types at their
// addresses, and the registers and stack arguments each function takes (a post-script, after the analysis).
// Argument: the list tools/ghidra/prepare.py writes (types.txt).
import java.io.BufferedReader;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.ByteDataType;
import ghidra.program.model.data.CharDataType;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DoubleDataType;
import ghidra.program.model.data.FloatDataType;
import ghidra.program.model.data.IntegerDataType;
import ghidra.program.model.data.ShortDataType;
import ghidra.program.model.data.SignedByteDataType;
import ghidra.program.model.data.StructureDataType;
import ghidra.program.model.data.UnsignedIntegerDataType;
import ghidra.program.model.data.UnsignedShortDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.ParameterImpl;
import ghidra.program.model.listing.Variable;
import ghidra.program.model.listing.VariableStorage;
import ghidra.program.model.symbol.SourceType;

public class RobotechTypes extends GhidraScript {
    private final Map<String, DataType> types = new HashMap<>();

    private DataType many(DataType one, int count) {
        return count > 0 ? new ArrayDataType(one, count, one.getLength()) : one;
    }

    @Override
    public void run() throws Exception {
        types.put("u8", ByteDataType.dataType);
        types.put("s8", SignedByteDataType.dataType);
        types.put("u16", UnsignedShortDataType.dataType);
        types.put("s16", ShortDataType.dataType);
        types.put("u32", UnsignedIntegerDataType.dataType);
        types.put("s32", IntegerDataType.dataType);
        types.put("f32", FloatDataType.dataType);
        types.put("f64", DoubleDataType.dataType);
        types.put("char", CharDataType.dataType);
        Map<String, StructureDataType> structures = new HashMap<>();
        List<String[]> variables = new ArrayList<>();
        List<String[]> signatures = new ArrayList<>();
        int fields = 0, failed = 0;
        try (BufferedReader reader = new BufferedReader(new FileReader(getScriptArgs()[0]))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String[] f = line.trim().split("\\s+");
                if (f[0].equals("struct")) {
                    structures.put(f[1], new StructureDataType(f[1], Integer.parseInt(f[2], 16)));
                } else if (f[0].equals("field")) {
                    DataType type = many(types.get(f[4]), Integer.parseInt(f[5]));
                    try {
                        structures.get(f[1]).replaceAtOffset(Integer.parseInt(f[2], 16), type, type.getLength(), f[3], null);
                        fields++;
                    } catch (Exception e) {
                        failed++;
                    }
                } else if (f[0].equals("var")) {
                    variables.add(f);
                } else if (f[0].equals("sig")) {
                    signatures.add(f);
                }
            }
        }
        for (Map.Entry<String, StructureDataType> entry : structures.entrySet()) {
            types.put(entry.getKey(), currentProgram.getDataTypeManager()
                    .addDataType(entry.getValue(), DataTypeConflictHandler.REPLACE_HANDLER));
        }
        println(structures.size() + " structures, " + fields + " fields, " + failed + " not placed");

        int typed = 0;
        failed = 0;
        for (String[] f : variables) {
            DataType one = types.get(f[3]);
            if (one == null) {
                failed++;
                continue;
            }
            DataType type = many(one, Integer.parseInt(f[4]));
            Address address = toAddr(Long.parseLong(f[1], 16));
            try {
                clearListing(address, address.add(type.getLength() - 1));
                createData(address, type);
                typed++;
            } catch (Exception e) {
                failed++;
            }
        }
        println(typed + " variables typed, " + failed + " not");

        int signed = 0;
        failed = 0;
        // a word of no type yet, so that the decompiler works out whether it is a pointer
        DataType word = ghidra.program.model.data.Undefined4DataType.dataType;
        for (String[] f : signatures) {
            Function function = getFunctionAt(toAddr(Long.parseLong(f[1], 16)));
            if (function == null) {
                failed++;
                continue;
            }
            try {
                List<Variable> parameters = new ArrayList<>();
                for (String register : f[3].split(",")) {
                    parameters.add(new ParameterImpl("in_" + register, word,
                            currentProgram.getRegister(register.toUpperCase()), currentProgram));
                }
                int arguments = Integer.parseInt(f[2]);
                for (int i = 0; i < arguments; i++) {
                    parameters.add(new ParameterImpl("arg" + i, word,
                            new VariableStorage(currentProgram, 4 + 4 * i, 4), currentProgram));
                }
                function.updateFunction(null, null, parameters,
                        Function.FunctionUpdateType.CUSTOM_STORAGE, true, SourceType.USER_DEFINED);
                signed++;
            } catch (Exception e) {
                failed++;
            }
        }
        println(signed + " functions given their registers and arguments, " + failed + " not");
    }
}

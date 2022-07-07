/*
 * Copyright (c) 2022, Oracle and/or its affiliates. All rights reserved.
 * DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
 *
 * This code is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License version 2 only, as
 * published by the Free Software Foundation.  Oracle designates this
 * particular file as subject to the "Classpath" exception as provided
 * by Oracle in the LICENSE file that accompanied this code.
 *
 * This code is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
 * version 2 for more details (a copy is included in the LICENSE file that
 * accompanied this code).
 *
 * You should have received a copy of the GNU General Public License version
 * 2 along with this work; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
 *
 * Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
 * or visit www.oracle.com if you need additional information or have any
 * questions.
 */
package com.oracle.mxtool.jacoco.lcov;

import java.io.IOException;
import java.io.Writer;
import java.util.HashMap;
import java.util.Map;
import java.util.TreeMap;

import org.jacoco.core.analysis.IBundleCoverage;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.ICounter;
import org.jacoco.core.analysis.ILine;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.analysis.IPackageCoverage;
import org.jacoco.core.analysis.ISourceFileCoverage;
import org.jacoco.report.IReportGroupVisitor;
import org.jacoco.report.ISourceFileLocator;

import com.oracle.mxtool.jacoco.JacocoReport;

public class LcovGroupHandler implements IReportGroupVisitor {
    private final Writer writer;
    private final Map<String, Map<String, IClassCoverage>> sourceToClassCoverage;
    private final Map<String, ISourceFileCoverage> sourceToFileCoverage;

    LcovGroupHandler(Writer writer) {
        this.writer = writer;
        this.sourceToClassCoverage = new TreeMap<>();
        this.sourceToFileCoverage = new TreeMap<>();
    }

    LcovGroupHandler(Writer writer, Map<String, Map<String, IClassCoverage>> sourceToClassCoverage, Map<String, ISourceFileCoverage> sourceToFileCoverage) {
        this.writer = writer;
        this.sourceToClassCoverage = sourceToClassCoverage;
        this.sourceToFileCoverage = sourceToFileCoverage;
    }

    @Override
    public void visitBundle(IBundleCoverage bundle, ISourceFileLocator iSourceFileLocator) {
        for (IPackageCoverage pkgCoverage : bundle.getPackages()) {
            for (IClassCoverage clsCoverage : pkgCoverage.getClasses()) {
                String fileName = ((JacocoReport.MultiDirectorySourceFileLocator) iSourceFileLocator).getSourceFilePath(clsCoverage.getPackageName(), clsCoverage.getSourceFileName());
                if (fileName == null) {
                    continue;
                }
                if (!sourceToClassCoverage.containsKey(fileName)) {
                    sourceToClassCoverage.put(fileName, new TreeMap<>());
                }
                sourceToClassCoverage.get(fileName).put(clsCoverage.getName(), clsCoverage);
            }
            for (ISourceFileCoverage srcCoverage : pkgCoverage.getSourceFiles()) {
                String fileName = ((JacocoReport.MultiDirectorySourceFileLocator) iSourceFileLocator).getSourceFilePath(srcCoverage.getPackageName(), srcCoverage.getName());
                if (fileName == null) {
                    continue;
                }
                sourceToFileCoverage.put(fileName, srcCoverage);
            }
        }
    }

    @Override
    public IReportGroupVisitor visitGroup(String name) {
        return new LcovGroupHandler(this.writer, this.sourceToClassCoverage, this.sourceToFileCoverage);
    }

    protected void visitEnd() throws IOException {
        writer.write("TN:\n");
        for (String sourceFile : sourceToClassCoverage.keySet()) {
            processSourceFile(sourceFile);
        }
    }

    private void processSourceFile(String sourceFile) throws IOException {
        writer.write(String.format("SF:%s\n", sourceFile));

        ISourceFileCoverage srcCoverage = sourceToFileCoverage.get(sourceFile);
        if (srcCoverage != null) {
            // List methods, including methods from nested classes, in FN/FNDA pairs
            for (IClassCoverage clsCoverage : sourceToClassCoverage.get(sourceFile).values()) {
                if (!clsCoverage.containsCode()) {
                    continue;
                }
                Map<String, Integer> fndas = new HashMap<>();
                for (IMethodCoverage mthCoverage : clsCoverage.getMethods()) {
                    String name = constructFunctionName(mthCoverage, clsCoverage.getName());
                    // <line number of function start>,<function name>
                    writer.write(String.format("FN:%d,%s\n", mthCoverage.getFirstLine(), name));
                    fndas.put(name, mthCoverage.getMethodCounter().getCoveredCount());
                }

                for (Map.Entry<String, Integer> fnda : fndas.entrySet()) {
                    // <execution count>,<function name>
                    writer.write(String.format("FNDA:%d,%s\n", fnda.getValue(), fnda.getKey()));
                }

                // <number of functions found>
                writer.write(String.format("FNF:%d\n", clsCoverage.getMethodCounter().getTotalCount()));
                // <number of function hit>
                writer.write(String.format("FNH:%d\n", clsCoverage.getMethodCounter().getCoveredCount()));
            }

            // List of DA entries matching source lines
            int firstLine = srcCoverage.getFirstLine();
            int lastLine = srcCoverage.getLastLine();
            int numberOfBranchesFound = 0;
            int numberOfBranchesHit = 0;
            for (int line = firstLine; line <= lastLine; line++) {
                ILine iLine = srcCoverage.getLine(line);
                int numberOfLineBranches = iLine.getBranchCounter().getMissedCount() + iLine.getBranchCounter().getCoveredCount();
                numberOfBranchesFound += numberOfLineBranches;

                if (iLine.getStatus() != ICounter.EMPTY && numberOfLineBranches != 0) {
                    for (int i = 0; i < numberOfLineBranches; i++) {
                        int branchVisits = i < iLine.getBranchCounter().getCoveredCount() ? 1 : 0;
                        if (branchVisits > 0) {
                            numberOfBranchesHit++;
                        }
                        // TODO BRDA <line number>,<block number>,<branch number>,<taken>
                    }
                }
            }

            // <number of branches found>
            writer.write(String.format("BRF:%d\n", numberOfBranchesFound));
            // <number of branches hit>
            writer.write(String.format("BRH:%d\n", numberOfBranchesHit));

            int lh = 0;
            int lf = 0;
            for (int line = firstLine; line <= lastLine; line++) {
                if (srcCoverage.getLine(line).getStatus() != ICounter.EMPTY) {
                    // <line number>,<execution count>[,<checksum>]
                    // Report if line was hit or not, we do not have execution counts
                    writer.write(String.format("DA:%d,%d\n", line, srcCoverage.getLine(line).getStatus() == ICounter.NOT_COVERED ? 0 : 1));
                    lf++;
                    if (srcCoverage.getLine(line).getStatus() != ICounter.NOT_COVERED) {
                        lh++;
                    }
                }
            }

            // <number of lines with a non-zero execution count>
            writer.write(String.format("LH:%d\n", lh));
            writer.write(String.format("LF:%d\n", lf)); // <number of instrumented lines>
        }
        writer.write("end_of_record\n");
    }

    private static String constructFunctionName(IMethodCoverage mthCoverage, String clsName) {
        return clsName + "::" + mthCoverage.getName() + "" + mthCoverage.getDesc();
    }

}

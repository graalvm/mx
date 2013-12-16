/*
 * Copyright (c) 2011, 2013, Oracle and/or its affiliates. All rights reserved.
 * DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
 *
 * This code is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License version 2 only, as
 * published by the Free Software Foundation.
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
import java.io.*;
import java.net.URISyntaxException;
import java.net.URL;
import java.util.*;
import java.util.regex.*;


/**
 * A program to check the existence and correctness of the copyright notice on a given set of sources.
 * Sources are defined to be those under management by Mercurial and various options are available
 * to limit the set of sources scanned.
 */
public class CheckCopyright {

    static class YearInfo {

        final int firstYear;
        final int lastYear;

        YearInfo(int firstYear, int lastYear) {
            this.firstYear = firstYear;
            this.lastYear = lastYear;
        }

        @Override
        public boolean equals(Object other) {
            final YearInfo yearInfo = (YearInfo) other;
            return yearInfo.firstYear == firstYear && yearInfo.lastYear == lastYear;
        }

        @Override
        public int hashCode() {
            return firstYear ^ lastYear;
        }
    }

    static class Info extends YearInfo {

        final String fileName;

        Info(String fileName, int firstYear, int lastYear) {
            super(firstYear, lastYear);
            this.fileName = fileName;
        }

        @Override
        public String toString() {
            return fileName + " " + firstYear + ", " + lastYear;
        }
    }

    private static abstract class CopyrightHandler {
    	enum CommentType{
    		STAR, HASH
    	}
    	
        private static Map<String, CopyrightHandler> copyrightMap;
        private static String copyrightFiles = ".*/makefile|.*/Makefile|.*\\.sh|.*\\.bash|.*\\.mk|.*\\.java|.*\\.c|.*\\.h|.*\\.py|.*\\.g|.*\\.r";
        private static Pattern copyrightFilePattern;
        
        protected final String suffix;
        private CopyrightHandler customHandler;
        
        CopyrightHandler(CommentType commentType) {
            this.suffix = commentType.name().toLowerCase();
            initCopyrightMap();
        }
        
        void addCustomhandler(CopyrightHandler copyrightHandler) {
        	this.customHandler = copyrightHandler;
        }
        
        /**
         * Add @code extension to files handled by this {@code CopyrightKind}
         */
        protected void updateMap(String extension) {
        	copyrightMap.put(extension, this);
        }

        static void addCopyrightFilesPattern(String pattern) {
            copyrightFiles += "|" + pattern;
        }

        protected abstract void readCopyrights()  throws IOException;
        
        protected abstract Matcher getMatcher(String fileName, String fileContent) throws IOException;
        
        protected abstract String getText(String fileName) throws IOException ;
        
        protected abstract boolean handlesFile(String fileName);
        
        /**
         * Checks that the Oracle copyright year info was correct.
         * @return {@code false} if the year info was incorrect and was not fixed otherwise return {@code true}
         * @throws IOException
         */
        protected abstract boolean checkYearInfo(String fileName, String fileContent, Matcher matcher, Info info) throws IOException;
        
        static String getCopyrightText(String fileName) throws IOException {
        	return getCopyrightHandler(fileName).getText(fileName);
        }
        
        private static CopyrightHandler getCopyrightHandler(String fileName) {
        	initCopyrightMap();
            if (!copyrightFilePattern.matcher(fileName).matches()) {
                return null;
            }
            CopyrightHandler ck = getDefaultHandler(fileName);
            if (ck.customHandler != null && ck.customHandler.handlesFile(fileName)) {
            	return ck.customHandler;
            } else {
            	return ck;
            }
        }

        private static void initCopyrightMap() {
            if (copyrightMap == null) {
                copyrightMap = new HashMap<String, CopyrightHandler>();
                copyrightFilePattern = Pattern.compile(copyrightFiles);
            }        	
        }

        static CopyrightHandler getDefaultHandler(String fileName) {
            int index = fileName.lastIndexOf(File.separatorChar);
            if (index > 0) {
                fileName = fileName.substring(index + 1);
            }
            String ext = "";
            index = fileName.lastIndexOf('.');
            if (index > 0) {
                ext = fileName.substring(index + 1);
            }
            if (fileName.equals("makefile")) {
                ext = "mk";
            }
            CopyrightHandler ck = copyrightMap.get(ext);
            assert ck != null : fileName;     
        	return ck;
        }

        protected String readCopyright(InputStream is) throws IOException {
            byte[] b = new byte[16384];
            int n = is.read(b);
            is.close();
            return new String(b, 0, n);    		
    	}

    }
    
    private static class DefaultCopyrightHandler extends CopyrightHandler {
        private static String ORACLE_COPYRIGHT = "oracle.copyright";
        private static String ORACLE_COPYRIGHT_REGEX = "oracle.copyright.regex";

        private String copyrightRegex;
        private String copyright;
        Pattern copyrightPattern;

        DefaultCopyrightHandler(CopyrightHandler.CommentType commentType) throws IOException {
    		super(commentType);
    		if (commentType == CopyrightHandler.CommentType.STAR) {
    			updateMap("java");
    			updateMap("c");
    			updateMap("h");
    			updateMap("g");
    		} else {
    			updateMap("r");
    			updateMap("py");
    			updateMap("sh");
    			updateMap("mk");
    			updateMap("bash");
    			updateMap("");    		
    		}
    		readCopyrights();
    	}

    	private String readCopyright(String name) throws IOException {
    		String copyRightDir = COPYRIGHT_DIR.getValue();
    		String fileName = "copyrights/" + name + "." + suffix;
    		String copyrightPath;
    		if (copyRightDir != null) {
    			copyrightPath = new File(new File(copyRightDir), fileName).getAbsolutePath();
    		} else {
    			URL url = CheckCopyright.class.getResource(fileName);
    			try {
    			copyrightPath = url.toURI().getPath();
    			} catch (URISyntaxException ex) {
    				throw new IOException(ex);
    			}
    		}
            InputStream is = new FileInputStream(copyrightPath);
            return readCopyright(is);
        }
    	
    	@Override
        protected void readCopyrights()  throws IOException {
         	copyright = readCopyright(ORACLE_COPYRIGHT);
         	copyrightRegex =  readCopyright(ORACLE_COPYRIGHT_REGEX);
         	copyrightPattern = Pattern.compile(copyrightRegex, Pattern.DOTALL);
        }
    	
    	@Override
    	protected Matcher getMatcher(String fileName, String fileContent) {
            return copyrightPattern.matcher(fileContent);
    	}
    	
    	@Override
        protected String getText(String fileName) {
    		return copyright;
    	}
    	
    	@Override
    	protected boolean handlesFile(String fileName) {
    		return true;
    	}

    	@Override
        protected boolean checkYearInfo(String fileName, String fileContent, Matcher matcher, Info info) throws IOException {
            int yearInCopyright;
            int yearInCopyrightIndex;
            yearInCopyright = Integer.parseInt(matcher.group(2));
            yearInCopyrightIndex = matcher.start(2);
            if (yearInCopyright != info.lastYear) {
                System.out.println(fileName + " copyright last modified year " + yearInCopyright + ", hg last modified year " + info.lastYear);
                if (FIX.getValue()) {
                    // Use currentYear as that is what it will be when it's checked in!
                    System.out.println("updating last modified year of " + fileName + " to " + currentYear);
                    final int lx = yearInCopyrightIndex;
                    final String newContent = fileContent.substring(0, lx) + info.lastYear + fileContent.substring(lx + 4);
                    final FileOutputStream os = new FileOutputStream(fileName);
                    os.write(newContent.getBytes());
                    os.close();
                    return true;
                } else {
                	return false;
                }
            }
            return true;
    	}

    }
    
    private static class CustomCopyrightHandler extends CopyrightHandler {
    	private Map<String, String> overrides = new HashMap<String, String>();
    	private CopyrightHandler defaultHandler;
    	
    	CustomCopyrightHandler(CopyrightHandler.CommentType commentType, CopyrightHandler defaultHandler) {
    		super(commentType);
    		this.defaultHandler = defaultHandler;
    	}
    	
    	void addFile(String fileName, String copyright) {
    		overrides.put(fileName, copyright);
    	}

		@Override
		protected void readCopyrights() throws IOException {
		}

		@Override
		protected Matcher getMatcher(String fileName, String fileContent) throws IOException {
			String copyright = overrides.get(fileName);
			assert copyright != null : fileName;
			try (InputStream fs = new FileInputStream(copyright + "." + suffix + ".regex")) {
				return Pattern.compile(readCopyright(fs), Pattern.DOTALL).matcher(fileContent);
			}
		}

		@Override
		protected String getText(String fileName) throws IOException {
			String copyright = overrides.get(fileName);
			assert copyright != null : fileName;
			try (InputStream fs = new FileInputStream(copyright + "." + suffix)) {
				return readCopyright(fs);
			}
		}

		@Override
		protected boolean handlesFile(String fileName) {
			return overrides.get(fileName) != null;
		}

		@Override
        protected boolean checkYearInfo(String fileName, String fileContent, Matcher matcher, Info info) throws IOException {
			// This is a bit tacky
			String copyright = overrides.get(fileName);
			if (copyright.endsWith("no.copyright")) {
				return true;
			}
			return defaultHandler.checkYearInfo(fileName, fileContent, matcher, info);
		}
    }
    
	private static void initCopyrightKinds() throws IOException {
		CopyrightHandler starHandler = new DefaultCopyrightHandler(CopyrightHandler.CommentType.STAR);
		CopyrightHandler hashHandler = new DefaultCopyrightHandler(CopyrightHandler.CommentType.HASH);

		String customCopyrightDir = CUSTOM_COPYRIGHT_DIR.getValue();
		if (customCopyrightDir != null) {
			CustomCopyrightHandler customStarHandler = new CustomCopyrightHandler(CopyrightHandler.CommentType.STAR, starHandler);
			CustomCopyrightHandler customHashHandler = new CustomCopyrightHandler(CopyrightHandler.CommentType.HASH, hashHandler);
			starHandler.addCustomhandler(customStarHandler);
			hashHandler.addCustomhandler(customHashHandler);

			File overrides = new File(new File(customCopyrightDir), "overrides");
			if (overrides.exists()) {
				try (BufferedReader br = new BufferedReader(new FileReader(
						overrides))) {
					while (true) {
						String line = br.readLine();
						if (line == null) {
							break;
						}
						if (line.length() == 0 || line.startsWith("#")) {
							continue;
						}
						String[] parts = line.split(",");
						// filename,copyright-file
						CopyrightHandler defaultHandler = CopyrightHandler.getDefaultHandler(parts[0]);
						CustomCopyrightHandler customhandler = (CustomCopyrightHandler) defaultHandler.customHandler;
						customhandler.addFile(parts[0], new File(new File(customCopyrightDir), parts[1]).getAbsolutePath());
					}
				}
			}
		}
	}
    
    private static int currentYear = Calendar.getInstance().get(Calendar.YEAR);
    private static Options options = new Options();
    private static Option<Boolean> help = options.newBooleanOption("help", false, "Show help message and exit.");
    private static Option<String> COPYRIGHT_DIR = options.newStringOption("copyright-dir", null, "override default location of copyright files");
    private static Option<List<String>> FILES_TO_CHECK = options.newStringListOption("files", null, "list of files to check");
    private static Option<String> FILE_LIST = options.newStringOption("file-list", null, "file containing list of files to check");
    private static Option<Boolean> DIR_WALK = options.newBooleanOption("list-dir", false, "check all files in directory tree requiring a copyright (ls -R)");
    private static Option<Boolean> HG_ALL = options.newBooleanOption("hg-all", false, "check all hg managed files requiring a copyright (hg status --all)");
    private static Option<Boolean> HG_MODIFIED = options.newBooleanOption("hg-modified", false, "check all modified hg managed files requiring a copyright (hg status)");
    private static Option<Boolean> HG_OUTGOING = options.newBooleanOption("hg-outgoing", false, "check outgoing hg managed files requiring a copyright (hg outgoing)");
    private static Option<String> HG_LOG = options.newStringOption("hg-last", "0", "check hg managed files requiring a copyright in last N changesets (hg log -l N)");
    private static Option<List<String>> PROJECT = options.newStringListOption("projects", null, "filter files to specific projects");
    private static Option<String> OUTGOING_REPO = options.newStringOption("hg-repo", null, "override outgoing repository");
    private static Option<Boolean> EXHAUSTIVE = options.newBooleanOption("hg-exhaustive", false, "check all hg managed files");
    private static Option<Boolean> FIX = options.newBooleanOption("fix", false, "fix all copyright errors");
    private static Option<String> FILE_PATTERN = options.newStringOption("file-pattern", null, "append additional file patterns for copyright checks");
    private static Option<Boolean> REPORT_ERRORS = options.newBooleanOption("report-errors", false, "report non-fatal errors");
    private static Option<Boolean> HALT_ON_ERROR = options.newBooleanOption("halt-on-error", false, "continue after normally fatal error");
    private static Option<String> HG_PATH = options.newStringOption("hg-path", "hg", "path to hg executable");
    private static Option<Boolean> VERBOSE = options.newBooleanOption("verbose", false, "verbose output");
    private static Option<Boolean> VERY_VERBOSE = options.newBooleanOption("very-verbose", false, "very verbose output");
    private static Option<String> CUSTOM_COPYRIGHT_DIR = options.newStringOption("custom-copyright-dir", null, "file containing filenames with custom copyrights");

    private static String CANNOT_FOLLOW_FILE = "abort: cannot follow";
    private static String hgPath;
    private static boolean error;
//    private static File workSpaceDirectory;
    private static boolean verbose;
    private static boolean veryVerbose;
    
    public static void main(String[] args) {
        // parse the arguments
        options.parseArguments(args);
        if (help.getValue()) {
            options.printHelp();
            return;
        }
        
        verbose = VERBOSE.getValue();
        veryVerbose = VERY_VERBOSE.getValue();
        
        hgPath = HG_PATH.getValue();

        if (FILE_PATTERN.getValue() != null) {
            CopyrightHandler.addCopyrightFilesPattern(FILE_PATTERN.getValue());
        }

        try {
           initCopyrightKinds();
            List<String> filesToCheck = null;
            if (HG_ALL.getValue()) {
                filesToCheck = getAllFiles(true);
            } else if (HG_OUTGOING.getValue()) {
                filesToCheck = getOutgoingFiles();
            } else if (HG_MODIFIED.getValue()) {
                filesToCheck = getAllFiles(false);
            } else if (Integer.parseInt(HG_LOG.getValue()) > 0) {
                filesToCheck = getLastNFiles(Integer.parseInt(HG_LOG.getValue()));
            } else if (FILE_LIST.getValue() != null) {
                filesToCheck = readFileList(FILE_LIST.getValue());
            } else if (DIR_WALK.getValue()) {
            	filesToCheck = getDirWalkFiles();
            } else if (FILES_TO_CHECK.getValue() != null) {
                filesToCheck = FILES_TO_CHECK.getValue();
            } else {
            	// no option set, default to HG_ALL
            	filesToCheck = getAllFiles(true);
            }
            if (filesToCheck != null && filesToCheck.size() > 0) {
                processFiles(filesToCheck);
            } else {
                System.out.println("nothing to check");
            }
            System.exit(error ? 1 : 0);
        } catch (Exception ex) {
            System.err.println("processing failed: " + ex);
            ex.printStackTrace();
        }
    }

    private static void processFiles(List<String> fileNames) throws Exception {
        final List<String> projects = PROJECT.getValue();
        Calendar cal = Calendar.getInstance();
        for (String fileName : fileNames) {
            if (projects == null || isInProjects(fileName, projects)) {
            	if (verbose) {
            		System.out.println("checking " + fileName);
            	}
                try {
                	Info info = null;
                	if (DIR_WALK.getValue()) {
                		info = getFromLastModified(cal, fileName);
                	} else {
                		final List<String> logInfo = hglog(fileName);
                		if (logInfo.size() == 0) {
                			// an added file, so go with last modified
                			info = getFromLastModified(cal, fileName);
                		} else {
                			info = getInfo(fileName, true, logInfo);
                		}
                	}
                    checkFile(fileName, info);
                } catch (Exception e) {
                    System.err.println("COPYRIGHT CHECK WARNING: error while processing " + fileName);
                }
            }
        }
    }
    
    private static Info getFromLastModified(Calendar cal, String fileName) {
		File file = new File(fileName);
		cal.setTimeInMillis(file.lastModified());
		int year = cal.get(Calendar.YEAR);
		return new Info(fileName, year, year);    	
    }

    private static boolean isInProjects(String fileName, List<String> projects) {
        final int ix = fileName.indexOf(File.separatorChar);
        if (ix < 0) {
            return false;
        }
        final String fileProject = fileName.substring(0, ix);
        for (String project : projects) {
            if (fileProject.equals(project)) {
                return true;
            }
        }
        return false;
    }

    private static List<String> readFileList(String fileListName) throws IOException {
        final List<String> result = new ArrayList<String>();
        BufferedReader b = null;
        try {
            b = new BufferedReader(new FileReader(fileListName));
            while (true) {
                final String fileName = b.readLine();
                if (fileName == null) {
                    break;
                }
                if (fileName.length() == 0) {
                    continue;
                }
                result.add(fileName);
            }
        } finally {
            if (b != null) {
                b.close();
            }
        }
        return result;
    }

    private static Info getInfo(String fileName, boolean lastOnly, List<String> logInfo) {
        // process sequence of changesets
        int lastYear = 0;
        int firstYear = 0;
        String summary = null;
        int ix = 0;

        while (ix < logInfo.size()) {
            String s = logInfo.get(ix++);
            assert s.startsWith("changeset");
            s = logInfo.get(ix++);
            // process every entry in a given change set
            if (s.startsWith("tag")) {
                s = logInfo.get(ix++);
            }
            if (s.startsWith("branch")) {
                s = logInfo.get(ix++);
            }
            while (s.startsWith("parent")) {
                s = logInfo.get(ix++);
            }
            assert s.startsWith("user");
            s = logInfo.get(ix++);
            assert s.startsWith("date");
            final int csYear = getYear(s);
            summary = logInfo.get(ix++);
            assert summary.startsWith("summary");
            s = logInfo.get(ix++); // blank
            assert s.length() == 0;
            if (lastYear == 0 && summary.contains("change all copyright notices from Sun to Oracle")) {
                // special case of last change being the copyright change, which didn't
                // count as a change of last modification date!
                continue;
            }
            if (lastYear == 0) {
                lastYear = csYear;
                firstYear = lastYear;
            } else {
                firstYear = csYear;
            }
            // if we only want the last modified year, quit now
            if (lastOnly) {
                break;
            }

        }

        // Special case
        if (summary != null && summary.contains("Initial commit of VM sources")) {
            firstYear = 2007;
        }
        if (HG_MODIFIED.getValue()) {
            // We are only looking at modified and, therefore, uncommitted files.
            // This means that the lastYear value will be the current year once the
            // file is committed, so that is what we want to check against.
            lastYear = currentYear;
        }
        return new Info(fileName, firstYear, lastYear);
    }

    private static int getYear(String dateLine) {
        final String[] parts = dateLine.split(" ");
        assert parts[parts.length - 2].startsWith("20");
        return Integer.parseInt(parts[parts.length - 2]);
    }

    private static void checkFile(String c, Info info) throws IOException {
        String fileName = info.fileName;
        File file = new File(fileName);
        if (!file.exists()) {
            System.err.println("COPYRIGHT CHECK WARNING: file " + file + " doesn't exist");
            return;
        }
        int fileLength = (int) file.length();
        byte[] fileContentBytes = new byte[fileLength];
        FileInputStream is = new FileInputStream(file);
        is.read(fileContentBytes);
        is.close();
        final String fileContent = new String(fileContentBytes);
        CopyrightHandler copyrightHandler = CopyrightHandler.getCopyrightHandler(fileName);
        if (copyrightHandler != null) {
            Matcher copyrightMatcher = copyrightHandler.getMatcher(fileName, fileContent);        	
            if (copyrightMatcher.matches()) {
            	error = !copyrightHandler.checkYearInfo(fileName, fileContent, copyrightMatcher, info);
            } else {
            	// If copyright is missing, insert it, otherwise user has to manually fix existing copyright.
				if (!fileContent.contains("Copyright")) {
					System.out.print("file " + fileName + " has missing copyright");
					if (FIX.getValue()) {
						final FileOutputStream os = new FileOutputStream(file);
						os.write(CopyrightHandler.getCopyrightText(fileName)
								.getBytes());
						os.write(fileContentBytes);
						os.close();
						System.out.println("...fixed");
					} else {
						System.out.println();
						error = true;
					}
				} else {
					System.out.println("file " + fileName + " has malformed copyright" + (FIX.getValue() ? " not fixing" : ""));
					error = true;
				}
            }
        } else if (EXHAUSTIVE.getValue()) {
            System.out.println("ERROR: file " + fileName + " has no copyright");
            error = true;
        }
    }


    private static List<String> hglog(String fileName) throws Exception {
        final String[] cmd = new String[] {hgPath, "log", "-f", fileName};
        return exec(null, cmd, true);
    }

    private static List<String> getLastNFiles(int n) throws Exception {
        final String[] cmd = new String[] {hgPath, "log", "-v", "-l", Integer.toString(n)};
        return getFilesFiles(exec(null, cmd, false));
    }

    private static List<String> getAllFiles(boolean all) throws Exception {
        final String[] cmd;
        if (HG_MODIFIED.getValue()) {
            cmd = new String[] {hgPath,  "status"};
        } else {
            cmd = new String[] {hgPath,  "status",  "--all"};
        }
        List<String> output = exec(null, cmd, true);
        final List<String> result = new ArrayList<String>(output.size());
        for (String s : output) {
            final char ch = s.charAt(0);
            if (!(ch == 'R' || ch == 'I' || ch == '?' ||  ch == '!')) {
                result.add(s.substring(2));
            }
        }
        return result;
    }

    private static List<String> getOutgoingFiles() throws Exception {
        final String[] cmd;
        if (OUTGOING_REPO.getValue() == null) {
            cmd = new String[] {hgPath,  "-v", "outgoing"};
        } else {
            cmd = new String[] {hgPath,  "-v", "outgoing", OUTGOING_REPO.getValue()};
        }

        final List<String> output = exec(null, cmd, false); // no outgoing exits with result 1
        return getFilesFiles(output);
    }

    private static List<String> getFilesFiles(List<String> output) {
        // there may be multiple changesets so merge the "files:"
        final Map<String, String> outSet = new TreeMap<String, String>();
        for (String s : output) {
            if (s.startsWith("files:")) {
                int ix = s.indexOf(' ');
                while (ix < s.length() && s.charAt(ix) == ' ') {
                    ix++;
                }
                final String[] files = s.substring(ix).split(" ");
                for (String file : files) {
                    outSet.put(file, file);
                }
            }
        }
        return new ArrayList<String>(outSet.values());
    }
    
    private static List<String> getDirWalkFiles() {
    	File cwd = new File(System.getProperty("user.dir"));
    	ArrayList<String> result = new ArrayList<String>();
    	getDirWalkFiles(cwd, result);
    	// remove "user.dir" prefix to make files relative as per hg
    	String cwdPath = cwd.getAbsolutePath() + '/';
    	for (int i = 0; i < result.size(); i++) {
    		String path = result.get(i);
    		result.set(i, path.replace(cwdPath, ""));
    	}
    	return result;
    }
    
    private static void getDirWalkFiles(File dir, ArrayList<String> list) {
    	File[] files = dir.listFiles();
    	for (File file : files) {
    		if (ignoreFile(file.getName())) {
    			continue;
    		}
    		if (file.isDirectory()) {
    				getDirWalkFiles(file, list);
    		} else {
    			list.add(file.getAbsolutePath());
    		}
    	}
    }
    
    private static final String IGNORE_LIST = "\\.hg|.*\\.class|bin|src_gen";
    private static final Pattern ignorePattern = Pattern.compile(IGNORE_LIST);
    
    private static boolean ignoreFile(String name) {
    	return ignorePattern.matcher(name).matches();
    }

    private static List<String> exec(File workingDir, String[] command, boolean failOnError) throws IOException, InterruptedException {
        List<String> result = new ArrayList<String>();
        if (veryVerbose) {
            System.out.println("Executing process in directory: " + workingDir);
            for (String c : command) {
                System.out.println("  " + c);
            }
        }
        final Process process = Runtime.getRuntime().exec(command, null, workingDir);
        try {
            result = readOutput(process.getInputStream());
            final int exitValue = process.waitFor();
            if (exitValue != 0) {
                final List<String> errorResult = readOutput(process.getErrorStream());
                if (REPORT_ERRORS.getValue()) {
                    System.err.print("execution of command: ");
                    for (String c : command) {
                        System.err.print(c);
                        System.err.print(' ');
                    }
                    System.err.println("failed with result " + exitValue);
                    for (String e : errorResult) {
                        System.err.println(e);
                    }
                }
                if (failOnError && HALT_ON_ERROR.getValue()) {
                	if (!cannotFollowNonExistentFile(errorResult)) {
                		throw new Error("terminating");
                	}
                }
            }
        } finally {
            process.destroy();
        }
        return result;
    }

    private static boolean cannotFollowNonExistentFile(List<String> errorResult) {
        return errorResult.size() == 1 && errorResult.get(0).startsWith(CANNOT_FOLLOW_FILE);
    }

    private static List<String> readOutput(InputStream is) throws IOException {
        final List<String> result = new ArrayList<String>();
        BufferedReader bs = null;
        try {
            bs = new BufferedReader(new InputStreamReader(is));
            while (true) {
                final String line = bs.readLine();
                if (line == null) {
                    break;
                }
                result.add(line);
            }
        } finally {
            if (bs != null) {
                bs.close();
            }
        }
        return result;
    }
    
    private static class Options {
    	private static Map<String, Option<?>> optionMap  = new TreeMap<>();

    	private Option<Boolean> newBooleanOption(String name, boolean defaultValue, String help) {
    		Option<Boolean> option = new Option<Boolean>(name, help, defaultValue, false, false);
    		optionMap.put(key(name), option);
    		return option;
    	}
    	
    	private Option<String> newStringOption(String name, String defaultValue, String help) {
    		Option<String> option = new Option<String>(name, help, defaultValue);
    		optionMap.put(key(name), option);
    		return option;
    	}

    	private Option<List<String>> newStringListOption(String name, List<String> defaultValue, String help) {
    		Option<List<String>> option = new Option<List<String>>(name, help, defaultValue, true, true);
    		optionMap.put(key(name), option);
    		return option;
    	}
    	
    	private static String key(String name) {
    		return "--" + name;
    	}
    	
    	void parseArguments(String[] args) {
            for (int i = 0; i < args.length; i++) {
            	final String arg = args[i];
            	if (arg.startsWith("--")) {
            		Option<?> option = optionMap.get(arg);
            		if (option == null || (option.consumesNext() && i == args.length - 1)) {
            			System.out.println("usage:");
            			printHelp();
            			System.exit(1);
            		}
            		if (option.consumesNext()) {
            			i++;
            			option.setValue(args[i]);
            		} else {
            			option.setValue(true);
            		}
            	}
            }
    	}

        void printHelp() {
        	for (Map.Entry<String, Option<?>> entrySet : optionMap.entrySet()) {
        		System.out.printf("%24s  %s%n", entrySet.getKey(), entrySet.getValue().help);
        	}
        }
}
    
    private static class Option<T> {
    	private final String name;
    	private final String help;
    	private final boolean consumesNext;
    	private final boolean isList;
    	private T value;
    	
    	Option(String name, String help, T defaultValue, boolean consumesNext, boolean isList) {
    		this.name = name;
    		this.help = help;
    		this.value = defaultValue;
    		this.consumesNext = consumesNext;
    		this.isList = isList;
   		
    	}
    	
    	Option(String name, String help, T defaultValue) {
    		this(name, help, defaultValue, true, false);
    	}
    	
        T getValue() {
    		return value;
    	}
        
        boolean consumesNext() {
        	return consumesNext;
        }
        
 	   @SuppressWarnings("unchecked")
       void setValue(boolean value) {
        	this.value = (T) new Boolean(value);
        }
        
 	   @SuppressWarnings("unchecked")
        void setValue(String value) {
 		   if (isList) {
 			   String[] parts = value.split(",");
 			   this.value = (T) Arrays.asList(parts);
 		   } else {
 			   this.value = (T) value;
 		   }
        }
 	   
 	   @SuppressWarnings("unused")
 	   String getName() {
 		   return name;
 	   }
    }
    
}
